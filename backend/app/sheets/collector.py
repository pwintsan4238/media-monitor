"""Crawl sources and turn new articles into spreadsheet rows. Pure logic: no Google, no database.

The Sheet itself is the memory: URLs and content hashes already in it are skipped, so a run only
adds what is new. Rows are append-only (an article that changes later is not rewritten).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Protocol

from ..crawler.discovery import discover
from ..crawler.extract import (MIN_TEXT, canonicalize_url, clean_text, content_hash, detect_language,
                               extract_page, html_to_text, looks_like_zawgyi, make_excerpt)
from ..crawler.http import BlockedByRobots, FetchError, Fetcher

log = logging.getLogger("mm.sheets")

HEADERS = ["published_at", "source", "title", "url", "author", "category", "language", "excerpt",
           "keywords", "indexed_at", "image_url", "content", "canonical_url", "content_hash", "duplicate_of"]
COL = {name: i for i, name in enumerate(HEADERS)}
MAX_CELL = 45_000          # Google Sheets allows 50,000 characters per cell
PAGE_BUDGET = 40           # article pages fetched per source per run; the rest are picked up next run
MAX_CONSECUTIVE_FAILS = 5


class Store(Protocol):
    def existing(self) -> tuple[set[str], dict[str, str]]: ...   # (canonical urls, content_hash -> url)
    def append(self, rows: list[list[str]]) -> None: ...
    def write_status(self, rows: list[list[str]]) -> None: ...


@dataclass
class SourceStatus:
    source: str
    status: str = "ok"        # ok | partial | failed | restricted
    found: int = 0
    new: int = 0
    skipped: int = 0
    deferred: int = 0
    duplicates: int = 0
    note: str = ""
    errors: list[str] = field(default_factory=list)

    def row(self, when: str) -> list[str]:
        return [self.source, when, self.status, str(self.found), str(self.new), str(self.skipped),
                str(self.deferred), self.note[:500]]


STATUS_HEADERS = ["source", "last_run_utc", "status", "found", "new", "already_in_sheet", "deferred", "note"]


def source_from_dict(d: dict):
    """Adapt a seed-style dict to what discover() expects."""
    return SimpleNamespace(name=d["name"], method=d.get("method", "rss"), rss_url=d.get("rss_url"),
                           sitemap_url=d.get("sitemap_url"), scrape_config=d.get("scrape_config") or {},
                           language=d.get("language", "my"), base_url=d["base_url"])


def _ts(d: datetime | None) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if d else ""


def collect_source(src, fetcher: Fetcher, urls: set[str], hashes: dict[str, str], st: SourceStatus,
                   now: datetime) -> list[list[str]]:
    cfg = src.scrape_config or {}
    budget, fails = int(cfg.get("max_page_fetches", PAGE_BUDGET)), 0
    res = discover(src, fetcher, max_urls=int(cfg.get("max_items", 200)))
    st.found, st.errors = len(res.items), list(res.errors)
    rows: list[list[str]] = []
    for item in res.items:
        canon = canonicalize_url(item.url)
        if canon in urls:
            st.skipped += 1
            continue
        feed_text = html_to_text(item.content_html)
        page = None
        if len(feed_text) < MIN_TEXT:
            if budget <= 0 or fails >= MAX_CONSECUTIVE_FAILS:
                st.deferred += 1
                continue
            budget -= 1
            try:
                resp = fetcher.get(item.url)
                page = extract_page(resp.content, str(resp.url))
                fails = 0
            except BlockedByRobots as e:
                fails = MAX_CONSECUTIVE_FAILS
                st.errors.append(str(e))
                st.deferred += 1
                continue
            except FetchError as e:
                fails += 1
                st.errors.append(str(e)[:200])
                st.deferred += 1
                continue
        title = clean_text(item.title) or (page.title if page else "") or ""
        if not title:
            st.errors.append(f"No title found for {item.url}")
            continue
        content = feed_text if len(feed_text) >= MIN_TEXT else (page.text if page else "")
        cats = item.categories or (page.categories if page else [])
        tags = list(dict.fromkeys([*cats[1:], *(page.tags if page else [])]))[:15]
        published = item.published_at or (page.published_at if page else None)
        h = content_hash(title, content)
        original = hashes.get(h) if len(content) >= MIN_TEXT else None
        if looks_like_zawgyi(title + content):
            st.errors.append(f"Possible Zawgyi-encoded text (not converted): {item.url}")
        row = [""] * len(HEADERS)
        row[COL["published_at"]] = _ts(published)
        row[COL["source"]] = src.name
        row[COL["title"]] = title
        row[COL["url"]] = item.url
        row[COL["author"]] = clean_text(item.author) or (page.author if page else "") or ""
        row[COL["category"]] = cats[0] if cats else ""
        row[COL["language"]] = detect_language(title + " " + content) or src.language
        row[COL["excerpt"]] = make_excerpt(content) if content else make_excerpt(
            html_to_text(item.excerpt) or (page.description if page else "") or "")
        row[COL["keywords"]] = "; ".join(tags)
        row[COL["indexed_at"]] = _ts(now)
        row[COL["image_url"]] = item.image_url or (page.image if page else "") or ""
        row[COL["content"]] = content[:MAX_CELL]
        row[COL["canonical_url"]] = canon
        row[COL["content_hash"]] = h
        row[COL["duplicate_of"]] = original or ""
        if original:
            st.duplicates += 1
        rows.append(row)
        urls.add(canon)
        hashes.setdefault(h, item.url)
        st.new += 1
    if res.restricted and not res.items:
        st.status, st.note = "restricted", "Blocked by the site's robots.txt; not monitored"
    elif not res.items:
        st.status = "failed"
    elif st.new + st.skipped == 0:
        st.status = "failed"  # URLs were listed but the site would not serve any article
    elif st.errors:
        st.status = "partial"
    if not st.note and st.errors:
        st.note = "; ".join(dict.fromkeys(st.errors))
    if st.deferred:
        st.note = (f"{st.deferred} more waiting for the next run. " + st.note).strip()
    return rows


def run(sources: list[dict], store: Store, fetcher_factory: Callable[[], Fetcher] = Fetcher,
        now: datetime | None = None) -> list[SourceStatus]:
    now = now or datetime.now(timezone.utc)
    urls, hashes = store.existing()
    statuses: list[SourceStatus] = []
    for d in sources:
        src = source_from_dict(d)
        st = SourceStatus(src.name)
        fetcher = None
        try:
            fetcher = fetcher_factory()
            rows = collect_source(src, fetcher, urls, hashes, st, now)
            if rows:
                store.append(rows)  # write per source so one failure never loses earlier work
        except Exception as e:  # a crashing source must not stop the others
            log.exception("source %s crashed", src.name)
            st.status, st.note = "failed", f"{type(e).__name__}: {e}"[:300]
        finally:
            if fetcher is not None:
                fetcher.close()
        log.info("%s: %s found=%d new=%d skipped=%d deferred=%d", st.source, st.status, st.found, st.new,
                 st.skipped, st.deferred)
        statuses.append(st)
    store.write_status([s.row(_ts(now)) for s in statuses])
    return statuses
