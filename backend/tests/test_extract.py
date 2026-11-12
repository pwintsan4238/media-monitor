import unicodedata

from app.crawler.extract import (canonicalize_url, content_hash, detect_language, extract_page, html_to_text,
                                 looks_like_zawgyi, make_excerpt)


def test_canonical_url_strips_noise_but_keeps_real_query():
    a = canonicalize_url("HTTP://Example.org:80/news/a-1/?utm_source=fb&id=7&fbclid=x#comments")
    assert a == "https://example.org/news/a-1?id=7"
    assert canonicalize_url("https://example.org/news/a-1?id=7") == a
    assert canonicalize_url("https://example.org/news/a-1/?utm_medium=x") == "https://example.org/news/a-1"
    assert canonicalize_url("https://example.org/") == "https://example.org/"
    assert canonicalize_url("https://example.org//a///b/") == "https://example.org/a/b"


def test_hash_ignores_invisible_chars_and_spacing_but_not_content():
    t = "မြန်မာ စီးပွားရေး"
    assert content_hash(t, "ဆောင်းပါး​ စာသား") == content_hash(t, "ဆောင်းပါး   စာသား")
    assert content_hash(t, "a") != content_hash(t, "b")


def test_html_to_text_keeps_paragraphs_and_drops_scripts():
    html = "<div><script>x()</script><p>ပထမ အပိုဒ်</p><p>ဒုတိယ အပိုဒ်</p></div>"
    assert html_to_text(html) == "ပထမ အပိုဒ်\n\nဒုတိယ အပိုဒ်"
    assert html_to_text(None) == ""


def test_excerpt_never_splits_a_burmese_cluster():
    text = "မြန်မာနိုင်ငံ၏စီးပွားရေးဖွံ့ဖြိုးတိုးတက်မှု" * 30  # no spaces at all
    for limit in range(60, 140):
        ex = make_excerpt(text, limit).rstrip("…")
        nxt = text[len(ex)] if len(ex) < len(text) else ""
        assert not nxt or unicodedata.category(nxt) not in ("Mn", "Mc"), limit
        assert not ex.endswith("္")


def test_excerpt_prefers_sentence_boundary():
    text = ("ပထမစာကြောင်း။ " * 3 + "ဒုတိယစာကြောင်းရှည်ကြီး") * 12
    assert make_excerpt(text, 100).rstrip("…").endswith("။")


def test_language_detection():
    assert detect_language("မြန်မာနိုင်ငံ စီးပွားရေး သတင်း အကြောင်းအရာ ဖော်ပြချက်") == "my"
    assert detect_language("The economy of Myanmar has contracted sharply this year") == "en"
    assert detect_language("hi") is None


def test_zawgyi_heuristic_flags_legacy_encoding_only():
    unicode_text = "မြန်မာနိုင်ငံ၏စီးပွားရေးဖွံ့ဖြိုးတိုးတက်မှု" * 5
    assert not looks_like_zawgyi(unicode_text)
    assert looks_like_zawgyi("ၠၡၢၣၤၥၦၧ" * 10 + "က" * 20)


PAGE = """<html><head><title>Site | Headline</title>
<link rel="canonical" href="https://ex.org/news/42"/>
<meta property="og:image" content="https://ex.org/i.jpg"/></head><body>
<nav>Home About</nav><article><h1>Real headline here</h1>
""" + "".join(f"<p>This is paragraph number {i} of a reasonably long article body with enough words in it.</p>"
              for i in range(8)) + "</article><footer>Copyright</footer></body></html>"


def test_extract_page_gets_body_and_canonical():
    page = extract_page(PAGE.encode(), "https://ex.org/news/42?utm_source=x")
    assert "paragraph number 3" in page.text
    assert "Copyright" not in page.text
    assert page.canonical == "https://ex.org/news/42"


def test_extract_page_on_junk_does_not_crash():
    page = extract_page(b"<html></html>", "https://ex.org/x")
    assert page.text == "" and page.title is None
