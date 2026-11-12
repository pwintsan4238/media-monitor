"""Pipeline tests: real database, mocked network."""
import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.crawler.http import Fetcher
from app.crawler.pipeline import crawl_source
from app.db import engine
from app.models import Article, ArticleVersion, Source

A, B = "https://pipe-a.invalid", "https://pipe-b.invalid"
BODY = "ဒီနေ့သတင်း အပိုဒ် {i} ဆိုင်ရာ အသေးစိတ် ဖော်ပြချက်များ ရေးသားထားပါသည် ထပ်မံ၍ အချက်အလက်များ ဖြည့်စွက်ပါသည်။"


def burmese(n=8, tag=""):
    return "".join(f"<p>{BODY.format(i=i)}{tag}</p>" for i in range(n))


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate>"
        + (f"<content:encoded><![CDATA[{c}]]></content:encoded>" if c else "") + "</item>"
        for t, u, d, c in items)
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>x</title>{body}</channel></rss>")


class Net:
    """Mock site: routes maps URL -> (status, body); records every request."""
    def __init__(self, routes):
        self.routes, self.hits = routes, []

    def fetcher(self):
        def handler(req: httpx.Request):
            self.hits.append(str(req.url))
            status, body = self.routes.get(str(req.url), (404, ""))
            return httpx.Response(status, content=body.encode() if isinstance(body, str) else body)
        return Fetcher(transport=httpx.MockTransport(handler), check_public=False, default_delay=0)

    def page_hits(self):
        return [h for h in self.hits if "/feed" not in h and "robots" not in h and "sitemap" not in h]


@pytest.fixture()
def db():
    with Session(engine()) as s:
        s.execute(delete(Source).where(Source.base_url.like("https://pipe-%")))
        s.commit()
        yield s
        s.rollback()
        s.execute(delete(Source).where(Source.base_url.like("https://pipe-%")))
        s.commit()


def make_source(db, base=A, **kw):
    kw = {"rss_url": f"{base}/feed", "method": "rss", **kw}
    s = Source(name="Pipe " + base[-9:], base_url=base, **kw)
    db.add(s)
    db.commit()
    return s


def run(db, src, net):
    return crawl_source(db, src, trigger="test", fetcher=net.fetcher())


def count(db, src=None):
    q = select(func.count()).select_from(Article)
    return db.scalar(q.where(Article.source_id == src.id) if src else q)


D1 = "Wed, 11 Nov 2026 10:00:00 +0000"


def test_feed_with_full_text_is_stored_without_fetching_pages(db):
    src = make_source(db)
    net = Net({f"{A}/feed": (200, rss(("မြန်မာ စီးပွားရေး", f"{A}/a/1?utm_source=x", D1, burmese())))})
    r = run(db, src, net)
    assert (r.new_count, r.status) == (1, "success")
    assert net.page_hits() == []
    a = db.scalar(select(Article).where(Article.source_id == src.id))
    assert a.title == "မြန်မာ စီးပွားရေး" and a.canonical_url == f"{A}/a/1".replace("http:", "https:")
    assert a.url == f"{A}/a/1?utm_source=x"  # original link preserved for display
    assert a.language == "my" and a.published_at.year == 2026 and len(a.content) > 200
    assert a.content_hash and a.excerpt and not a.content_limited


def test_rerun_is_a_noop_and_makes_no_page_requests(db):
    src = make_source(db)
    net = Net({f"{A}/feed": (200, rss(("T", f"{A}/a/1", D1, burmese())))})
    run(db, src, net)
    r = run(db, src, net)
    assert (r.new_count, r.updated_count, r.stats["unchanged"]) == (0, 0, 1)
    assert count(db, src) == 1


def test_changed_content_updates_in_place_keeps_version_and_publication_date(db):
    src = make_source(db)
    net = Net({f"{A}/feed": (200, rss(("T", f"{A}/a/1", D1, burmese())))})
    run(db, src, net)
    net.routes[f"{A}/feed"] = (200, rss(("T (updated)", f"{A}/a/1", "Thu, 12 Nov 2026 09:00:00 +0000",
                                         burmese(tag=" ပြင်ဆင်ထားသည်"))))
    r = run(db, src, net)
    assert r.updated_count == 1 and count(db, src) == 1
    a = db.scalar(select(Article).where(Article.source_id == src.id))
    assert a.title == "T (updated)" and a.published_at.day == 11  # original date preserved
    v = db.scalars(select(ArticleVersion).where(ArticleVersion.article_id == a.id)).all()
    assert len(v) == 1 and v[0].title == "T"


def test_sitemap_style_item_fetches_page_once_and_extracts(db):
    src = make_source(db, rss_url=None, sitemap_url=f"{A}/sitemap.xml", method="sitemap")
    sm = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{A}/post/7</loc></url></urlset>'
    page = (f"<html><head><title>S</title></head><body><article><h1>ခေါင်းစဉ် စမ်းသပ်ချက်</h1>"
            f"{burmese()}</article></body></html>")
    net = Net({f"{A}/sitemap.xml": (200, sm), f"{A}/post/7": (200, page)})
    r = run(db, src, net)
    assert r.new_count == 1 and net.page_hits() == [f"{A}/post/7"]
    a = db.scalar(select(Article).where(Article.source_id == src.id))
    assert "ခေါင်းစဉ်" in a.title and len(a.content) > 200
    run(db, src, net)
    assert net.page_hits() == [f"{A}/post/7"]  # not fetched again


def test_same_text_under_another_url_on_same_site_is_not_stored_twice(db):
    src = make_source(db)
    net = Net({f"{A}/feed": (200, rss(("T", f"{A}/a/1", D1, burmese()), ("T", f"{A}/amp/a/1", D1, burmese())))})
    r = run(db, src, net)
    assert count(db, src) == 1 and r.stats["duplicates"] == 1


def test_same_text_on_another_source_is_kept_but_linked(db):
    a, b = make_source(db, A), make_source(db, B)
    run(db, a, Net({f"{A}/feed": (200, rss(("T", f"{A}/a/1", D1, burmese())))}))
    r = run(db, b, Net({f"{B}/feed": (200, rss(("T", f"{B}/x/9", D1, burmese())))}))
    assert r.new_count == 1 and r.stats["cross_source_duplicates"] == 1
    orig = db.scalar(select(Article).where(Article.source_id == a.id))
    copy = db.scalar(select(Article).where(Article.source_id == b.id))
    assert copy.duplicate_of_id == orig.id and orig.duplicate_of_id is None


def test_page_budget_defers_the_rest_to_the_next_run(db):
    src = make_source(db, rss_url=None, sitemap_url=f"{A}/sitemap.xml", method="sitemap",
                      scrape_config={"max_page_fetches": 2})
    urls = [f"{A}/post/{i}" for i in range(5)]
    sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    routes = {f"{A}/sitemap.xml": (200, sm)}
    for i, u in enumerate(urls):
        routes[u] = (200, f"<html><body><article><h1>ခေါင်းစဉ် {i}</h1>{burmese(tag=str(i))}</article></body></html>")
    net = Net(routes)
    r1 = run(db, src, net)
    assert r1.new_count == 2 and r1.stats["deferred"] == 3 and count(db, src) == 2
    run(db, src, net)
    run(db, src, net)
    assert count(db, src) == 5  # backfills across runs without refetching earlier pages
    assert len(net.page_hits()) == 5


def test_repeated_fetch_failures_stop_the_crawl_and_are_reported(db):
    src = make_source(db, rss_url=None, sitemap_url=f"{A}/sitemap.xml", method="sitemap")
    urls = [f"{A}/post/{i}" for i in range(12)]
    sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    net = Net({f"{A}/sitemap.xml": (200, sm), **{u: (403, "no") for u in urls}})
    r = run(db, src, net)
    assert len(net.page_hits()) == 5  # gave up after 5 refusals instead of hammering the site
    assert r.status == "failed" and "403" in r.log
    db.refresh(src)
    assert src.health in ("degraded", "failing")


def test_short_body_is_stored_as_limited_not_passed_off_as_full_text(db):
    src = make_source(db)
    net = Net({f"{A}/feed": (200, rss(("ခေါင်းစဉ်", f"{A}/a/9", D1, "<p>တိုတို</p>")))})
    page = "<html><body><article><h1>ခေါင်းစဉ်</h1><p>တိုတို</p></article></body></html>"
    net.routes[f"{A}/a/9"] = (200, page)
    r = run(db, src, net)
    a = db.scalar(select(Article).where(Article.source_id == src.id))
    assert r.new_count == 1 and a.content_limited and r.stats["limited"] == 1


def test_missing_date_stays_null(db):
    src = make_source(db)
    feed = ('<rss version="2.0"><channel><title>x</title><item><title>T</title><link>' + f"{A}/a/5"
            + "</link><description>" + "x" * 10 + "</description></item></channel></rss>")
    net = Net({f"{A}/feed": (200, feed), f"{A}/a/5": (200, "<html><body><p>hi</p></body></html>")})
    run(db, src, net)
    a = db.scalar(select(Article).where(Article.source_id == src.id))
    assert a.published_at is None
