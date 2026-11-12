"""Find article URLs (and whatever metadata comes free) from RSS feeds and sitemaps."""
import calendar
import gzip
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup
from lxml import etree

from .http import BlockedByRobots, FetchError, Fetcher

log = logging.getLogger("mm.crawler.discovery")

_SKIP_CHILD = re.compile(r"categor|tag|author|user|page|product|attachment|taxonomy|archive", re.I)
_WANT_CHILD = re.compile(r"post|news|article|story", re.I)
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)


@dataclass
class Item:
    url: str
    title: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    author: str | None = None
    excerpt: str | None = None
    content_html: str | None = None
    image_url: str | None = None
    categories: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    method: str | None = None
    items: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    restricted: bool = False


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# -- RSS ---------------------------------------------------------------------
def discover_rss(fetcher: Fetcher, url: str) -> list[Item]:
    resp = fetcher.get(url)
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise FetchError(f"Not a usable feed (no entries): {url}")
    items = []
    for e in feed.entries:
        link = e.get("link")
        if not link:
            continue
        pub = e.get("published_parsed") or e.get("updated_parsed")
        content = e.get("content")
        image = None
        for m in e.get("media_content", []) + e.get("media_thumbnail", []):
            if m.get("url"):
                image = m["url"]
                break
        if not image:
            for enc in e.get("enclosures", []):
                if str(enc.get("type", "")).startswith("image") and enc.get("href"):
                    image = enc["href"]
                    break
        if not image:  # many feeds only carry the picture inline in the article HTML
            html = (content[0].get("value") if content else None) or e.get("summary")
            if html:
                img = BeautifulSoup(html, "lxml").find("img", src=True)
                if img and str(img["src"]).startswith(("http://", "https://")):
                    image = img["src"]
        items.append(Item(
            url=link.strip(),
            title=(e.get("title") or "").strip() or None,
            published_at=datetime.fromtimestamp(calendar.timegm(pub), timezone.utc) if pub else None,
            author=e.get("author") or None,
            excerpt=e.get("summary") or None,
            content_html=content[0].get("value") if content else None,
            image_url=image,
            categories=[t["term"] for t in e.get("tags", []) if t.get("term")],
        ))
    return items


# -- Sitemap -----------------------------------------------------------------
def _xml(content: bytes):
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    root = etree.fromstring(content, _PARSER)
    if root is None:
        raise FetchError("Sitemap is not valid XML")
    return root


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _children_text(el) -> dict[str, str]:
    out = {}
    for c in el.iter():
        name = _local(c)
        if name and c.text and c.text.strip() and name not in out:
            out[name] = c.text.strip()
    return out


def discover_sitemap(fetcher: Fetcher, url: str, max_urls: int = 200, max_children: int = 3,
                     depth: int = 0, opts: dict | None = None) -> list[Item]:
    """opts (per-source scrape_config): url_include (regex an article URL must match),
    child_order='last' (newest children are listed last), sort='id_desc' (newest = highest numeric id)."""
    opts = opts or {}
    root = _xml(fetcher.get(url).content)
    kind = _local(root)
    if kind == "sitemapindex":
        if depth >= 2:
            return []
        kids = []
        for sm in root:
            f = _children_text(sm)
            if f.get("loc"):
                kids.append((f["loc"], _dt(f.get("lastmod"))))
        wanted = [k for k in kids if _WANT_CHILD.search(k[0])]
        kids = wanted or [k for k in kids if not _SKIP_CHILD.search(k[0])]
        if opts.get("child_order") == "last":
            # Newest chunks are listed last, but trailing chunks may hold non-articles (tags,
            # categories): scan backwards until `max_children` chunks actually yield articles.
            kids, scan_limit = kids[::-1], 12
        else:
            kids.sort(key=lambda k: k[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            scan_limit = max_children
        items: list[Item] = []
        errors = []
        matched = 0
        for loc, _ in kids[:scan_limit]:
            try:
                got = discover_sitemap(fetcher, loc, max_urls, max_children, depth + 1, opts)
            except BlockedByRobots:
                raise
            except FetchError as e:
                errors.append(str(e))
                continue
            if got:
                items += got
                matched += 1
                if matched >= max_children:
                    break
        if not items and errors:
            raise FetchError("; ".join(errors))
        return _finish(items, max_urls, opts)
    if kind != "urlset":
        raise FetchError(f"Unrecognised sitemap root <{kind}>")
    items = []
    for u in root:
        loc = None
        title = pub = image = None
        for c in u.iter():
            n = _local(c)
            txt = (c.text or "").strip()
            if n == "loc" and loc is None and txt:
                loc = txt
            elif n == "title" and txt and not title:
                title = txt
            elif n == "publication_date" and txt:
                pub = _dt(txt)
            elif n == "lastmod" and txt and not pub:
                pass
            elif n == "loc" and loc and txt and not image and c.getparent() is not None \
                    and _local(c.getparent()) == "image":
                image = txt
        f = _children_text(u)
        if loc:
            items.append(Item(url=loc, title=title, published_at=pub, updated_at=_dt(f.get("lastmod")),
                              image_url=image))
    return _finish(items, max_urls, opts)


def _finish(items: list[Item], max_urls: int, opts: dict | None = None) -> list[Item]:
    opts = opts or {}
    include = re.compile(opts["url_include"]) if opts.get("url_include") else None
    seen, out = set(), []
    for it in items:
        if it.url not in seen and (include is None or include.search(it.url)):
            seen.add(it.url)
            out.append(it)
    if opts.get("sort") == "id_desc":
        def num(i):
            m = re.search(r"(\d+)/?$", i.url)
            return int(m.group(1)) if m else -1
        out.sort(key=num, reverse=True)
    else:
        floor = datetime.min.replace(tzinfo=timezone.utc)
        out.sort(key=lambda i: i.published_at or i.updated_at or floor, reverse=True)
    return out[:max_urls]


# -- Orchestration -------------------------------------------------------------
def discover(source, fetcher: Fetcher, max_urls: int = 200) -> DiscoveryResult:
    """Try the source's configured method first, then fall back (RSS -> sitemap)."""
    cfg = source.scrape_config or {}
    plan: list[tuple[str, str]] = []
    if source.method == "sitemap" and source.sitemap_url:
        plan.append(("sitemap", source.sitemap_url))
    if source.rss_url:
        plan.append(("rss", source.rss_url))
    if source.sitemap_url and ("sitemap", source.sitemap_url) not in plan:
        plan.append(("sitemap", source.sitemap_url))
    if source.method == "rss":  # configured method goes first
        plan.sort(key=lambda p: p[0] != "rss")
    result = DiscoveryResult()
    if not plan:
        result.errors.append("No feed or sitemap URL configured for this source")
        return result
    for method, url in plan:
        try:
            if method == "rss":
                items = discover_rss(fetcher, url)
            else:
                items = discover_sitemap(fetcher, url, max_urls=max_urls,
                                         max_children=int(cfg.get("max_child_sitemaps", 3)), opts=cfg)
        except BlockedByRobots as e:
            result.restricted = True
            result.errors.append(f"[{method}] {e}")
            continue
        except FetchError as e:
            result.errors.append(f"[{method}] {e}")
            continue
        except Exception as e:  # parsing surprises must not kill the whole run
            log.exception("discovery crashed for %s", url)
            result.errors.append(f"[{method}] unexpected {type(e).__name__}: {e}")
            continue
        if items:
            result.method, result.items = method, items[:max_urls]
            return result
        result.errors.append(f"[{method}] found no articles at {url}")
    return result
