import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import auth
from .admin import router as admin_router
from .config import settings
from .db import engine, get_db
from .export import router as export_router
from .models import Article, CrawlRun, Source

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mm")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # A crawl thread dies with the process; don't leave its run showing "running" forever.
    try:
        with Session(engine()) as s:
            stale = s.scalars(select(CrawlRun).where(CrawlRun.status == "running")).all()
            for r in stale:
                r.status, r.finished_at = "failed", datetime.now(timezone.utc)
                r.log = (r.log + "\n" if r.log else "") + "Interrupted: the server restarted during this crawl"
            s.commit()
            if stale:
                log.warning("marked %d interrupted crawl run(s) as failed", len(stale))
    except Exception:
        log.exception("could not clean up stale crawl runs")
    yield


app = FastAPI(title="Media Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(admin_router)
app.include_router(export_router)


class LoginIn(BaseModel):
    username: str
    password: str


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    if not auth.verify_login(body.username, body.password):
        log.warning("failed login for %r", body.username)
        raise HTTPException(401, "Invalid username or password")
    response.set_cookie(
        auth.COOKIE,
        auth.make_token(body.username),
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_hours * 3600,
    )
    return {"username": body.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: str = auth.Authed):
    return {"username": user}


@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db), user: str = auth.Authed):
    counts = dict(db.execute(select(Article.source_id, func.count()).group_by(Article.source_id)).all())
    return [
        {
            "id": s.id, "name": s.name, "base_url": s.base_url, "enabled": s.enabled,
            "method": s.method, "health": s.health, "health_note": s.health_note,
            "last_success_at": s.last_success_at, "article_count": counts.get(s.id, 0),
        }
        for s in db.scalars(select(Source).order_by(Source.name))
    ]
