"""Crawl one source: discover -> (fetch+extract) -> dedupe -> upsert, recording what happened."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Article, ArticleVersion, CrawlRun, Source
from .discovery import DiscoveryResult, Item, discover
from .extract import (MIN_TEXT, PageData, canonicalize_url, clean_text, content_hash, detect_language,
                      extract_page, html_to_text, looks_like_zawgyi, make_excerpt)
from .http import BlockedByRobots, FetchError, Fetcher

log = logging.getLogger("mm.crawler.pipeline")

DEFAULT_PAGE_BUDGET = 40      # article pages fetched per run; the rest are picked up by later runs
MAX_CONSECUTIVE_FAILS = 5     # stop hitting a site that keeps refusing us


@dataclass
class Stats:
    discovered: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0   # same text already stored from the same source (URL variants): not stored
    cross_source_duplicates: int = 0  # stored, but linked to the original
    deferred: int = 0     # new articles not fetched yet because the page budget ran out
    failed: int = 0
    limited: int = 0      # stored with headline/excerpt only (body unavailable)
    zawgyi_suspects: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class _Budget:
    pages: int
    consecutive_fails: int = 0
    abort: bool = False


# -- health bookkeeping (shared with the admin "test" endpoint) -----------------------
def robots_label(fetcher: Fetcher, source: Source, res: DiscoveryResult) -> str:
    if res.restricted and not res.items:
        return "restricted"
    return {"found": "allowed", "none": "no_robots", "unreachable": "unreachable"}[
        fetcher.robots_for(source.base_url).status]


def apply_health(s: Source, ok: bool, errors: list[str], robots: str):
    s.robots_status = robots
    if ok:
        s.health, s.health_note = "ok", None
        s.consecutive_failures, s.last_error = 0, None
        s.last_success_at = datetime.now(timezone.utc)
        if errors:
            s.health_note = "Partial problems: " + errors[0][:250]
    else:
        s.consecutive_failures += 1
        s.last_error = "; ".join(errors)[:2000]
        if robots == "restricted":
            s.health, s.health_note = "limited", "Blocked by the site's robots.txt; not monitored"
        else:
            s.health = "failing" if s.consecutive_failures >= 3 else "degraded"
            s.health_note = s.last_error[:300]


# -- per-article work ---------------------------------------------------------------
def _same_host(a: str, b: str) -> bool:
    return (urlsplit(a).hostname or "").lower() == (urlsplit(b).hostname or "").lower()


def _process(db: Session, source: Source, item: Item, fetcher: Fetcher, st: Stats, budget: _Budget):
    canon = canonicalize_url(item.url)
    art = db.scalar(select(Article).where(Article.canonical_url == canon))

    feed_text = html_to_text(item.content_html)
    feed_has_body = len(feed_text) >= MIN_TEXT
    source_changed = bool(art and item.updated_at and art.updated_at and item.updated_at > art.updated_at)
    need_fetch = not feed_has_body and (art is None or art.content_limited or source_changed)

    page: PageData | None = None
    if need_fetch:
        if budget.abort or budget.pages <= 0:
            st.deferred += 1 if art is None else 0
            st.unchanged += 1 if art is not None else 0
            return
        budget.pages -= 1
        try:
            resp = fetcher.get(item.url)
            page = extract_page(resp.content, str(resp.url))
            budget.consecutive_fails = 0
        except BlockedByRobots as e:
            budget.abort = True
            st.errors.append(str(e))
            st.deferred += 1 if art is None else 0
            return
        except FetchError as e:
            budget.consecutive_fails += 1
            if budget.consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                budget.abort = True
                st.errors.append(f"Stopped fetching pages after {MAX_CONSECUTIVE_FAILS} failures in a row")
            st.failed += 1
            st.errors.append(str(e)[:200])
            return
    elif art is not None and not feed_has_body:
        st.unchanged += 1
        return

    title = clean_text(item.title) or (page.title if page else None) or ""
    if not title:
        st.failed += 1
        st.errors.append(f"No title found for {item.url}")
        return

    content = feed_text if feed_has_body else (page.text if page else "")
    limited = len(content) < MIN_TEXT
    published = item.published_at or (page.published_at if page else None)
    author = clean_text(item.author) or (page.author if page else None)
    image = item.image_url or (page.image if page else None)
    cats = item.categories or (page.categories if page else [])
    category = cats[0][:200] if cats else None
    keywords = list(dict.fromkeys([*cats[1:], *(page.tags if page else [])]))[:15]
    excerpt = (make_excerpt(content) if content else
               make_excerpt(html_to_text(item.excerpt) or (page.description if page else "") or ""))
    lang = detect_language(title + " " + content) or source.language
    h = content_hash(title, content)
    if looks_like_zawgyi(title + content):
        st.zawgyi_suspects += 1

    # The page may declare a different canonical URL: honour it only if it stays on the same host.
    if page and page.canonical and _same_host(page.canonical, item.url):
        c2 = canonicalize_url(page.canonical)
        if urlsplit(c2).path not in ("", "/") and c2 != canon:
            other = db.scalar(select(Article).where(Article.canonical_url == c2))
            if other is not None:
                art, canon = other, c2
            elif art is None:
                canon = c2

    now = datetime.now(timezone.utc)
    if art is None:
        dup = None if limited else db.scalar(select(Article).where(Article.content_hash == h).order_by(Article.id))
        if dup is not None and dup.source_id == source.id:
            st.duplicates += 1  # same text, different URL, same site
            return
        db.add(Article(
            source_id=source.id, title=title, url=item.url, canonical_url=canon, published_at=published,
            author=author, content=content, excerpt=excerpt, image_url=image, keywords=keywords,
            category=category, language=lang, content_hash=h, content_limited=limited,
            duplicate_of_id=dup.id if dup else None, updated_at=now))
        st.new += 1
        st.cross_source_duplicates += 1 if dup else 0
        st.limited += 1 if limited else 0
    elif art.content_hash != h and not (limited and not art.content_limited):
        # Content changed: keep the old version, update in place. Never overwrite a known publication date.
        db.add(ArticleVersion(article_id=art.id, title=art.title, content=art.content,
                              content_hash=art.content_hash))
        art.title, art.content, art.excerpt, art.content_hash = title, content, excerpt, h
        art.content_limited, art.language, art.updated_at = limited, lang, now
        art.author = author or art.author
        art.image_url = image or art.image_url
        art.category = category or art.category
        art.keywords = keywords or art.keywords
        art.published_at = art.published_at or published
        st.updated += 1
    else:
        # Unchanged (or the refetch lost the body, e.g. a paywall appeared: keep what we had).
        art.published_at = art.published_at or published
        art.author = art.author or author
        art.image_url = art.image_url or image
        if need_fetch:
            art.updated_at = now  # so we don't refetch on every run
        st.unchanged += 1


# -- one run ------------------------------------------------------------------------
def crawl_source(db: Session, source: Source, run: CrawlRun | None = None, trigger: str = "schedule",
                 fetcher: Fetcher | None = None) -> CrawlRun:
    cfg = source.scrape_config or {}
    if run is None:
        run = CrawlRun(source_id=source.id, trigger=trigger)
        db.add(run)
        db.flush()
    own_fetcher = fetcher is None
    fetcher = fetcher or Fetcher()
    st = Stats()
    budget = _Budget(pages=int(cfg.get("max_page_fetches", DEFAULT_PAGE_BUDGET)))
    try:
        res = discover(source, fetcher, max_urls=int(cfg.get("max_items", 200)))
        st.discovered = len(res.items)
        st.errors.extend(res.errors)
        for item in res.items:
            try:
                _process(db, source, item, fetcher, st, budget)
                db.commit()
            except Exception as e:  # one bad article must not sink the run
                db.rollback()
                log.exception("failed processing %s", item.url)
                st.failed += 1
                st.errors.append(f"{item.url}: {type(e).__name__}: {e}"[:300])
        robots = robots_label(fetcher, source, res)
    finally:
        if own_fetcher:
            fetcher.close()

    # Success means we actually obtained or confirmed articles. Merely discovering URLs that the
    # site then refused to serve (or that we deferred) is not a working source.
    ok = st.discovered > 0 and (st.new + st.updated + st.unchanged + st.duplicates) > 0
    apply_health(source, ok, st.errors, robots)
    run.finished_at = datetime.now(timezone.utc)
    run.discovered, run.new_count, run.updated_count = st.discovered, st.new, st.updated
    run.error_count = st.failed + len(res.errors)
    run.status = "failed" if not ok else ("partial" if st.errors else "success")
    run.stats = {"unchanged": st.unchanged, "duplicates": st.duplicates,
                 "cross_source_duplicates": st.cross_source_duplicates, "deferred": st.deferred,
                 "failed": st.failed, "limited": st.limited, "zawgyi_suspects": st.zawgyi_suspects,
                 "method": res.method}
    notes = []
    if st.deferred:
        notes.append(f"{st.deferred} new article(s) deferred to the next run (page budget)")
    if st.zawgyi_suspects:
        notes.append(f"{st.zawgyi_suspects} article(s) may be Zawgyi-encoded (not converted)")
    run.log = "\n".join([*notes, *dict.fromkeys(st.errors)][:60])
    db.commit()
    return run
