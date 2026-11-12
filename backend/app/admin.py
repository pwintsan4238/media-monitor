import logging
import threading
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import auth
from .crawler.discovery import DiscoveryResult, discover
from .crawler.http import Fetcher
from .crawler.pipeline import apply_health, crawl_source, robots_label
from .db import engine, get_db
from .models import Article, CrawlRun, Source

log = logging.getLogger("mm.admin")
router = APIRouter(prefix="/api/admin", dependencies=[auth.Authed])


def _http_url(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    p = urlparse(v)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("must be a full http(s) URL")
    return v


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    base_url: str
    rss_url: str | None = None
    sitemap_url: str | None = None
    method: Literal["rss", "sitemap"] = "rss"
    language: str = "my"
    enabled: bool = True
    crawl_interval_minutes: int = Field(default=60, ge=5, le=10080)
    scrape_config: dict = Field(default_factory=dict)

    _v = field_validator("base_url", "rss_url", "sitemap_url")(_http_url)


class SourceOut(SourceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    robots_status: str
    health: str
    health_note: str | None
    consecutive_failures: int
    last_success_at: datetime | None
    last_error: str | None
    article_count: int = 0


def _out(s: Source, db: Session) -> SourceOut:
    count = db.scalar(select(func.count()).select_from(Article).where(Article.source_id == s.id)) or 0
    o = SourceOut.model_validate(s)
    o.article_count = count
    return o


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Article.source_id, func.count()).group_by(Article.source_id)).all())
    out = []
    for s in db.scalars(select(Source).order_by(Source.name)):
        o = SourceOut.model_validate(s)
        o.article_count = counts.get(s.id, 0)
        out.append(o)
    return out


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db)):
    s = Source(**body.model_dump())
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A source with this base URL already exists")
    return _out(s, db)


def _get(db: Session, sid: int) -> Source:
    s = db.get(Source, sid)
    if not s:
        raise HTTPException(404, "Source not found")
    return s


@router.put("/sources/{sid}", response_model=SourceOut)
def update_source(sid: int, body: SourceIn, db: Session = Depends(get_db)):
    s = _get(db, sid)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A source with this base URL already exists")
    return _out(s, db)


@router.delete("/sources/{sid}")
def delete_source(sid: int, db: Session = Depends(get_db)):
    s = _get(db, sid)
    db.delete(s)  # cascades to its articles and crawl runs
    db.commit()
    return {"deleted": sid}


# -- dry run -----------------------------------------------------------------------
def _run_discovery(s: Source) -> tuple[DiscoveryResult, str]:
    fetcher = Fetcher()
    try:
        res = discover(s, fetcher)
        robots = robots_label(fetcher, s, res)
    finally:
        fetcher.close()
    return res, robots


@router.post("/sources/{sid}/test")
def test_source(sid: int, db: Session = Depends(get_db)):
    """Dry run: discover what would be collected. Stores no articles."""
    s = _get(db, sid)
    res, robots = _run_discovery(s)
    apply_health(s, bool(res.items), res.errors, robots)
    db.commit()
    return {
        "robots_status": robots, "method": res.method, "total": len(res.items),
        "with_title": sum(1 for i in res.items if i.title),
        "with_date": sum(1 for i in res.items if i.published_at),
        "with_content": sum(1 for i in res.items if i.content_html),
        "errors": res.errors,
        "sample": [{"url": i.url, "title": i.title, "published_at": i.published_at,
                    "has_content": bool(i.content_html)} for i in res.items[:10]],
    }


# -- real crawl (background) ----------------------------------------------------------
_running: set[int] = set()
_lock = threading.Lock()


def _spawn(fn):  # tests replace this to run synchronously
    threading.Thread(target=fn, daemon=True).start()


def start_crawl(db: Session, sid: int, trigger: str) -> int:
    """Create a run record and crawl in a background thread. Reused by the scheduler."""
    _get(db, sid)
    with _lock:
        if sid in _running:
            raise HTTPException(409, "A crawl for this source is already running")
        _running.add(sid)
    try:
        run = CrawlRun(source_id=sid, trigger=trigger)
        db.add(run)
        db.commit()
    except Exception:
        with _lock:
            _running.discard(sid)
        raise
    run_id = run.id

    def work():
        fetcher = Fetcher()
        try:
            with Session(engine()) as wdb:
                crawl_source(wdb, wdb.get(Source, sid), run=wdb.get(CrawlRun, run_id), fetcher=fetcher)
        except Exception as e:
            log.exception("crawl of source %s crashed", sid)
            with Session(engine()) as wdb:
                r = wdb.get(CrawlRun, run_id)
                r.status, r.finished_at = "failed", datetime.now(timezone.utc)
                r.log = f"Crawl crashed: {type(e).__name__}: {e}"[:2000]
                wdb.commit()
        finally:
            fetcher.close()
            with _lock:
                _running.discard(sid)

    _spawn(work)
    return run_id


@router.post("/sources/{sid}/crawl", status_code=202)
def crawl_now(sid: int, db: Session = Depends(get_db)):
    return {"run_id": start_crawl(db, sid, "manual"), "status": "running"}


def _run_dict(r: CrawlRun, name: str | None = None) -> dict:
    return {"id": r.id, "source_id": r.source_id, "source_name": name, "started_at": r.started_at,
            "finished_at": r.finished_at, "status": r.status, "trigger": r.trigger,
            "discovered": r.discovered, "new": r.new_count, "updated": r.updated_count,
            "errors": r.error_count, "stats": r.stats or {}, "log": r.log}


@router.get("/crawl-runs")
def crawl_runs(source_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = (select(CrawlRun, Source.name).join(Source, Source.id == CrawlRun.source_id)
         .order_by(CrawlRun.started_at.desc()).limit(min(limit, 200)))
    if source_id:
        q = q.where(CrawlRun.source_id == source_id)
    return [_run_dict(r, n) for r, n in db.execute(q)]


@router.get("/crawl-runs/{rid}")
def crawl_run(rid: int, db: Session = Depends(get_db)):
    r = db.get(CrawlRun, rid)
    if not r:
        raise HTTPException(404, "Run not found")
    return _run_dict(r)
