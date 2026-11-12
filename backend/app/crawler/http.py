"""Polite HTTP client: honest User-Agent, robots.txt, per-host rate limiting, SSRF guard.

Never tries to evade blocks: a 403/429, a robots disallow or a login wall is reported, not bypassed.
"""
import ipaddress
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
import truststore

from ..config import settings

log = logging.getLogger("mm.crawler.http")

MAX_REDIRECTS = 5


class FetchError(Exception):
    pass


class BlockedByRobots(FetchError):
    pass


def check_public_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to private/loopback addresses."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchError(f"Unsupported URL: {url}")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as e:
        raise FetchError(f"DNS lookup failed for {p.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise FetchError(f"Refusing to fetch non-public address for {p.hostname}")


@dataclass
class Robots:
    status: str  # found | none | unreachable
    parser: robotparser.RobotFileParser | None = None
    delay: float | None = None


class Fetcher:
    def __init__(self, user_agent: str | None = None, default_delay: float = 1.5, timeout: float = 25.0,
                 transport: httpx.BaseTransport | None = None, check_public: bool = True):
        self.user_agent = user_agent or settings.crawler_user_agent
        self.token = self.user_agent.split("/")[0].split()[0]
        self.default_delay = default_delay
        self.check_public = check_public
        # Verify TLS against the operating system's trust store (certificates stay verified).
        # This also works behind corporate proxies / antivirus that re-sign traffic.
        kwargs = {}
        if transport is None:
            kwargs["verify"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Language": "my,en;q=0.8"},
            timeout=timeout, follow_redirects=False, transport=transport, **kwargs,
        )
        self._robots: dict[str, Robots] = {}
        self._last_request: dict[str, float] = {}

    def close(self):
        self.client.close()

    # -- rate limiting ------------------------------------------------------
    def _wait(self, host: str, delay: float):
        last = self._last_request.get(host)
        if last is not None:
            gap = delay - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last_request[host] = time.monotonic()

    def _raw_get(self, url: str, delay: float) -> httpx.Response:
        for _ in range(MAX_REDIRECTS + 1):
            if self.check_public:
                check_public_url(url)
            resp = None
            for attempt in range(3):  # retry transient network errors with backoff (2s, 4s)
                self._wait(urlparse(url).netloc, delay)
                try:
                    resp = self.client.get(url)
                    break
                except httpx.TransportError as e:
                    if attempt == 2:
                        raise FetchError(f"{type(e).__name__}: {e}") from e
                    time.sleep(2 * (attempt + 1))
                except httpx.HTTPError as e:
                    raise FetchError(f"{type(e).__name__}: {e}") from e
            if resp.is_redirect and resp.headers.get("location"):
                url = urljoin(url, resp.headers["location"])
                continue
            return resp
        raise FetchError("Too many redirects")

    # -- robots.txt ---------------------------------------------------------
    def robots_for(self, url: str) -> Robots:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        try:
            resp = self._raw_get(f"{origin}/robots.txt", self.default_delay)
        except FetchError as e:
            log.warning("robots.txt unreachable for %s: %s", origin, e)
            info = Robots("unreachable")
        else:
            if resp.status_code == 200:
                rp = robotparser.RobotFileParser()
                rp.parse(resp.text.splitlines())
                info = Robots("found", rp, rp.crawl_delay(self.token) or rp.crawl_delay("*"))
            elif resp.status_code >= 500:
                info = Robots("unreachable")
            else:  # 404 etc.: no robots file means no restrictions
                info = Robots("none")
        self._robots[origin] = info
        return info

    def allowed(self, url: str) -> bool:
        r = self.robots_for(url)
        if r.status == "unreachable":
            return False  # be conservative: RFC 9309 says treat server errors as disallow
        if r.status == "none":
            return True
        return r.parser.can_fetch(self.token, url)

    # -- public API ---------------------------------------------------------
    def get(self, url: str) -> httpx.Response:
        if self.robots_for(url).status == "unreachable":
            # A network/TLS/5xx problem is not a robots block; report it as what it is.
            raise FetchError(f"Not fetched: could not retrieve robots.txt, so crawling permission is unknown ({url})")
        if not self.allowed(url):
            raise BlockedByRobots(f"Not fetched: the site's robots.txt disallows it ({url})")
        delay = max(self.default_delay, self.robots_for(url).delay or 0)
        resp = self._raw_get(url, delay)
        if resp.status_code in (401, 403):
            raise FetchError(f"HTTP {resp.status_code}: access refused by the site ({url})")
        if resp.status_code == 429:
            raise FetchError(f"HTTP 429: rate limited by the site ({url})")
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} for {url}")
        return resp
