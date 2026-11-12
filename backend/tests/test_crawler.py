import httpx
import pytest

from app.crawler.discovery import discover, discover_rss, discover_sitemap
from app.crawler.http import BlockedByRobots, FetchError, Fetcher, check_public_url

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>
<item><title>မြန်မာ စီးပွားရေး</title><link>https://ex.org/a/1</link>
<pubDate>Wed, 11 Nov 2026 10:00:00 +0000</pubDate><category>Economy</category>
<content:encoded><![CDATA[<p>ဆောင်းပါး</p>]]></content:encoded></item>
<item><title>No date</title><link>https://ex.org/a/2</link></item>
</channel></rss>"""

NEWS_SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:news="http://www.google.com/schemas/sitemap-news/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
<url><loc>https://ex.org/n/1</loc><lastmod>2026-11-11T23:00:00Z</lastmod>
<news:news><news:publication_date>2026-11-11T22:00:00Z</news:publication_date><news:title>Headline one</news:title></news:news>
<image:image><image:loc>https://ex.org/i.jpg</image:loc></image:image></url>
<url><loc>https://ex.org/n/2</loc><lastmod>2026-11-12T01:00:00Z</lastmod></url></urlset>"""


def make_fetcher(routes: dict[str, tuple[int, str]]):
    def handler(req: httpx.Request):
        status, body = routes.get(str(req.url), (404, "not found"))
        return httpx.Response(status, text=body)
    return Fetcher(transport=httpx.MockTransport(handler), check_public=False, default_delay=0)


def test_robots_disallow_blocks():
    f = make_fetcher({"https://ex.org/robots.txt": (200, "User-agent: *\nDisallow: /feed"),
                      "https://ex.org/feed": (200, RSS)})
    with pytest.raises(BlockedByRobots):
        f.get("https://ex.org/feed")


def test_missing_robots_means_allowed():
    f = make_fetcher({"https://ex.org/feed": (200, RSS)})
    assert f.get("https://ex.org/feed").status_code == 200


def test_robots_server_error_is_not_reported_as_a_block():
    f = make_fetcher({"https://ex.org/robots.txt": (503, ""), "https://ex.org/feed": (200, RSS)})
    with pytest.raises(FetchError) as e:
        f.get("https://ex.org/feed")
    assert not isinstance(e.value, BlockedByRobots)


def test_403_is_reported_not_bypassed():
    f = make_fetcher({"https://ex.org/feed": (403, "no")})
    with pytest.raises(FetchError, match="403"):
        f.get("https://ex.org/feed")


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost/x", "ftp://ex.org/x", "http://10.0.0.5/"])
def test_ssrf_guard(url):
    with pytest.raises(FetchError):
        check_public_url(url)


def test_rss_items_keep_burmese_text_and_missing_dates():
    items = discover_rss(make_fetcher({"https://ex.org/feed": (200, RSS)}), "https://ex.org/feed")
    assert [i.url for i in items] == ["https://ex.org/a/1", "https://ex.org/a/2"]
    assert items[0].title == "မြန်မာ စီးပွားရေး"
    assert items[0].published_at.year == 2026 and items[0].content_html == "<p>ဆောင်းပါး</p>"
    assert items[0].categories == ["Economy"]
    assert items[1].published_at is None  # never guessed


def test_rss_takes_thumbnail_from_inline_html_when_feed_has_no_image_field():
    feed = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>'
            '<item><title>A</title><link>https://ex.org/a</link><content:encoded><![CDATA['
            '<p><img src="https://ex.org/pic.jpg"/>text</p>]]></content:encoded></item>'
            '<item><title>B</title><link>https://ex.org/b</link><content:encoded><![CDATA['
            '<p><img src="data:image/gif;base64,AAAA"/>text</p>]]></content:encoded></item></channel></rss>')
    a, b = discover_rss(make_fetcher({"https://ex.org/feed": (200, feed)}), "https://ex.org/feed")
    assert a.image_url == "https://ex.org/pic.jpg"
    assert b.image_url is None  # inline data: URIs are not thumbnails


def test_rss_rejects_non_feed():
    with pytest.raises(FetchError):
        discover_rss(make_fetcher({"https://ex.org/feed": (200, "<html>hi</html>")}), "https://ex.org/feed")


def test_news_sitemap_metadata_and_order():
    items = discover_sitemap(make_fetcher({"https://ex.org/s.xml": (200, NEWS_SITEMAP)}), "https://ex.org/s.xml")
    by_url = {i.url: i for i in items}
    assert by_url["https://ex.org/n/1"].title == "Headline one"
    assert by_url["https://ex.org/n/1"].image_url == "https://ex.org/i.jpg"
    assert by_url["https://ex.org/n/1"].published_at.hour == 22
    assert items[0].url == "https://ex.org/n/2"  # newest (by lastmod) first


def _urlset(urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")


def test_index_scans_backwards_past_non_article_chunks_and_sorts_by_id():
    index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             + "".join(f"<sitemap><loc>https://ex.org/sm/{n}.xml</loc></sitemap>" for n in range(4))
             + "</sitemapindex>")
    f = make_fetcher({
        "https://ex.org/sitemap.xml": (200, index),
        "https://ex.org/sm/0.xml": (200, _urlset(["https://ex.org/about"])),
        "https://ex.org/sm/1.xml": (200, _urlset(["https://ex.org/post/5", "https://ex.org/post/9"])),
        "https://ex.org/sm/2.xml": (200, _urlset(["https://ex.org/post/20", "https://ex.org/post/12"])),
        "https://ex.org/sm/3.xml": (200, _urlset(["https://ex.org/tags/a", "https://ex.org/tags/b"])),
    })
    opts = {"url_include": r"/post/\d+$", "child_order": "last", "sort": "id_desc"}
    items = discover_sitemap(f, "https://ex.org/sitemap.xml", max_children=1, opts=opts)
    assert [i.url for i in items] == ["https://ex.org/post/20", "https://ex.org/post/12"]


class Src:
    def __init__(self, **kw):
        self.method, self.rss_url, self.sitemap_url, self.scrape_config = "rss", None, None, {}
        self.__dict__.update(kw)


def test_discover_falls_back_to_sitemap_and_records_why():
    f = make_fetcher({"https://ex.org/feed": (500, ""), "https://ex.org/s.xml": (200, NEWS_SITEMAP)})
    res = discover(Src(rss_url="https://ex.org/feed", sitemap_url="https://ex.org/s.xml"), f)
    assert res.method == "sitemap" and len(res.items) == 2
    assert res.errors and "[rss]" in res.errors[0]


def test_discover_reports_robots_restriction():
    f = make_fetcher({"https://ex.org/robots.txt": (200, "User-agent: *\nDisallow: /"),
                      "https://ex.org/feed": (200, RSS)})
    res = discover(Src(rss_url="https://ex.org/feed"), f)
    assert res.restricted and not res.items


def test_discover_without_any_url():
    res = discover(Src(), make_fetcher({}))
    assert not res.items and res.errors
