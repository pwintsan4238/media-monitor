"""Turn raw pages and feed HTML into clean, comparable article fields.

Everything here is pure (no network, no DB) so it is easy to test.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura
from bs4 import BeautifulSoup

MIN_TEXT = 200  # below this we treat the article body as unavailable ("limited")

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|igshid$|_hs|ref$|ref_src$)", re.I)
# Zero-width characters: Burmese sites use U+200B between phrases. We keep them in stored text
# (they help tokenisation) but ignore them when hashing so spacing differences don't defeat dedup.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿⁠"), None)


# -- URLs ---------------------------------------------------------------------
def canonicalize_url(url: str) -> str:
    """Stable key for 'the same page': lowercase host, https, no fragment/tracking params, no trailing slash."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)))
    return urlunsplit(("https", host + port, path, query, ""))


# -- text ---------------------------------------------------------------------
def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s).replace("\r", "")
    s = re.sub(r"[ \t\f\v ]+", " ", s)
    s = re.sub(r" ?\n ?", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "iframe"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    blocks = [b.get_text(" ", strip=True) for b in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "blockquote"])]
    text = "\n\n".join(b for b in blocks if b) or soup.get_text("\n", strip=True)
    return clean_text(text)


def _for_hash(s: str) -> str:
    s = unicodedata.normalize("NFC", s).translate(_INVISIBLE)
    return re.sub(r"\s+", " ", s).strip().lower()


def content_hash(title: str, content: str) -> str:
    return hashlib.sha256((_for_hash(title) + "\n" + _for_hash(content)).encode()).hexdigest()


def make_excerpt(text: str, limit: int = 300) -> str:
    """Cut on a sentence/phrase boundary where possible, and never inside a Burmese syllable cluster."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = limit
    window = text[max(0, limit - 80):limit]
    m = max((window.rfind(c) for c in (" ", "​", "။", "၊", ".", ",")), default=-1)
    if m >= 0:
        cut = max(0, limit - 80) + m + 1
    else:
        # no boundary: back off so we don't split a combining sequence or stop right after a virama
        while cut > 0 and (unicodedata.category(text[cut]) in ("Mn", "Mc") or text[cut - 1] == "္"):
            cut -= 1
    return text[:cut].rstrip() + "…"


def detect_language(text: str) -> str | None:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        return None
    burmese = sum(1 for c in letters if "က" <= c <= "႟")
    return "my" if burmese / len(letters) > 0.3 else "en"


def looks_like_zawgyi(text: str) -> bool:
    """Heuristic only. Zawgyi-encoded Burmese shows up as Myanmar code points that real Unicode
    Burmese almost never uses (U+1060-1097, U+1033-1034)."""
    mm = [c for c in text if "က" <= c <= "႟"]
    if len(mm) < 50:
        return False
    odd = sum(1 for c in mm if "ၠ" <= c <= "႗" or c in "ဳဴ")
    return odd / len(mm) > 0.03


# -- pages --------------------------------------------------------------------
@dataclass
class PageData:
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    text: str = ""
    image: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    canonical: str | None = None


def _as_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r"[;,]", v)]
    return [str(x).strip() for x in v if str(x).strip()]


def _parse_date(v) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def extract_page(content: bytes, url: str) -> PageData:
    doc = trafilatura.bare_extraction(content, url=url, with_metadata=True, include_comments=False,
                                      favor_recall=True)
    canonical = None
    try:
        soup = BeautifulSoup(content, "lxml")
        link = soup.find("link", rel="canonical")
        canonical = link.get("href") if link and link.get("href") else None
    except Exception:
        pass
    if doc is None:
        return PageData(canonical=canonical)
    g = (lambda k: doc.get(k)) if isinstance(doc, dict) else (lambda k: getattr(doc, k, None))
    return PageData(
        title=clean_text(g("title")) or None,
        author=clean_text(g("author")) or None,
        published_at=_parse_date(g("date")),
        text=clean_text(g("text")),
        image=g("image") or None,
        categories=_as_list(g("categories")),
        tags=_as_list(g("tags")),
        description=clean_text(g("description")) or None,
        canonical=canonical,
    )
