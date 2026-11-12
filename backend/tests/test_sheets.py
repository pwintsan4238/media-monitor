import httpx

from app.crawler.http import Fetcher
from app.sheets import collector
from app.sheets.collector import COL, HEADERS
from app.sheets.store import MemoryStore, search_formula

BODY = "ဒီနေ့သတင်း အပိုဒ် {i} ဆိုင်ရာ အသေးစိတ် ဖော်ပြချက်များ ရေးသားထားပါသည် ထပ်မံ၍ အချက်အလက်များ ဖြည့်စွက်ပါသည်။"
D1 = "Wed, 11 Nov 2026 10:00:00 +0000"


def body(n=8, tag=""):
    return "".join(f"<p>{BODY.format(i=i)}{tag}</p>" for i in range(n))


def rss(*items):
    xml = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{D1}</pubDate>"
                  f"<content:encoded><![CDATA[{c}]]></content:encoded></item>" for t, u, c in items)
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>x</title>{xml}</channel></rss>")


def factory(routes, hits=None):
    def make():
        def handler(req):
            if hits is not None:
                hits.append(str(req.url))
            status, text = routes.get(str(req.url), (404, ""))
            return httpx.Response(status, content=text.encode())
        return Fetcher(transport=httpx.MockTransport(handler), check_public=False, default_delay=0)
    return make


def src(name, base, **kw):
    return {"name": name, "base_url": base, "rss_url": f"{base}/feed", "method": "rss", **kw}


def test_column_letters_match_the_search_formula():
    # The Search tab's QUERY refers to columns by letter; this pins the layout it depends on.
    letter = lambda n: chr(ord("A") + HEADERS.index(n))
    assert [letter(n) for n in ("published_at", "source", "title", "url", "excerpt", "content",
                                "canonical_url", "content_hash")] == list("ABCDHLMN")
    f = search_formula()
    assert f.startswith("=IFERROR(QUERY(Articles!A2:O,") and f.count('"') % 2 == 0
    assert "lower(C) contains" in f and "lower(H) contains" in f and "lower(L) contains" in f


def test_new_articles_become_rows_and_rerun_adds_nothing():
    a = "https://sheet-a.invalid"
    routes = {f"{a}/feed": (200, rss(("မြန်မာ စီးပွားရေး", f"{a}/p/1?utm_source=x", body())))}
    store = MemoryStore()
    st = collector.run([src("A", a)], store, factory(routes))[0]
    assert (st.status, st.new, len(store.rows)) == ("ok", 1, 1)
    r = store.rows[0]
    assert r[COL["title"]] == "မြန်မာ စီးပွားရေး" and r[COL["source"]] == "A"
    assert r[COL["published_at"]] == "2026-11-11 10:00:00" and r[COL["language"]] == "my"
    assert r[COL["url"]].endswith("utm_source=x") and r[COL["canonical_url"]] == f"{a}/p/1"
    assert len(r[COL["content"]]) > 200 and r[COL["indexed_at"]]
    st2 = collector.run([src("A", a)], store, factory(routes))[0]
    assert (st2.new, st2.skipped, len(store.rows)) == (0, 1, 1)


def test_same_text_on_another_source_is_added_but_marked_duplicate():
    a, b = "https://sheet-a.invalid", "https://sheet-b.invalid"
    routes = {f"{a}/feed": (200, rss(("T", f"{a}/p/1", body()))), f"{b}/feed": (200, rss(("T", f"{b}/x/9", body())))}
    store = MemoryStore()
    collector.run([src("A", a), src("B", b)], store, factory(routes))
    assert len(store.rows) == 2
    assert store.rows[0][COL["duplicate_of"]] == "" and store.rows[1][COL["duplicate_of"]] == f"{a}/p/1"


def test_page_budget_defers_and_next_run_continues_without_refetching():
    a, hits = "https://sheet-a.invalid", []
    urls = [f"{a}/post/{i}" for i in range(5)]
    sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    routes = {f"{a}/sitemap.xml": (200, sm)}
    for i, u in enumerate(urls):
        routes[u] = (200, f"<html><body><article><h1>ခေါင်းစဉ် {i}</h1>{body(tag=str(i))}</article></body></html>")
    source = {"name": "A", "base_url": a, "method": "sitemap", "sitemap_url": f"{a}/sitemap.xml",
              "scrape_config": {"max_page_fetches": 2}}
    store = MemoryStore()
    f = factory(routes, hits)
    s1 = collector.run([source], store, f)[0]
    assert (s1.new, s1.deferred) == (2, 3) and "waiting for the next run" in s1.note
    collector.run([source], store, f)
    collector.run([source], store, f)
    assert len(store.rows) == 5
    assert len([h for h in hits if "/post/" in h]) == 5


def test_site_that_refuses_every_page_is_reported_failed_not_ok():
    a = "https://sheet-a.invalid"
    urls = [f"{a}/post/{i}" for i in range(8)]
    sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")
    routes = {f"{a}/sitemap.xml": (200, sm), **{u: (403, "no") for u in urls}}
    store = MemoryStore()
    st = collector.run([{"name": "A", "base_url": a, "method": "sitemap", "sitemap_url": f"{a}/sitemap.xml"}],
                       store, factory(routes))[0]
    assert st.status == "failed" and not store.rows and "403" in st.note


def test_robots_block_is_reported_as_restricted():
    a = "https://sheet-a.invalid"
    routes = {f"{a}/robots.txt": (200, "User-agent: *\nDisallow: /"), f"{a}/feed": (200, rss(("T", f"{a}/p/1", body())))}
    st = collector.run([src("A", a)], MemoryStore(), factory(routes))[0]
    assert st.status == "restricted"


def test_formula_like_titles_are_kept_verbatim_and_cells_are_capped():
    a = "https://sheet-a.invalid"
    routes = {f"{a}/feed": (200, rss(('=HYPERLINK("http://evil.example")', f"{a}/p/1", body(8000))))}
    store = MemoryStore()
    collector.run([src("A", a)], store, factory(routes))
    r = store.rows[0]
    assert r[COL["title"]] == '=HYPERLINK("http://evil.example")'  # safe: rows are written with RAW input
    assert len(r[COL["content"]]) <= collector.MAX_CELL


def test_one_crashing_source_does_not_stop_the_others_and_status_is_written():
    a, b = "https://sheet-a.invalid", "https://sheet-b.invalid"
    routes = {f"{b}/feed": (200, rss(("T", f"{b}/p/1", body())))}
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return factory(routes)()

    store = MemoryStore()
    sts = collector.run([src("A", a), src("B", b)], store, flaky)
    assert [s.status for s in sts] == ["failed", "ok"] and len(store.rows) == 1
    assert [r[0] for r in store.status_rows] == ["A", "B"] and store.status_rows[0][2] == "failed"
