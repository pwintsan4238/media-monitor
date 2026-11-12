import csv
import io

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.export import safe_cell
from app.main import app
from app.models import Article, Source

BASE = "https://export-test.invalid"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "tester")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"pw-for-tests", bcrypt.gensalt()).decode())
    with Session(engine()) as s:
        s.execute(delete(Source).where(Source.base_url == BASE))
        src = Source(name="Export Test", base_url=BASE)
        s.add(src)
        s.flush()
        s.add_all([
            Article(source_id=src.id, title='=HYPERLINK("http://evil.example","click")', url=f"{BASE}/1",
                    canonical_url=f"{BASE}/1", content="x", content_hash="e1", language="en"),
            Article(source_id=src.id, title="မြန်မာ စီးပွားရေး သတင်း", url=f"{BASE}/2", canonical_url=f"{BASE}/2",
                    content="y", content_hash="e2", language="my", keywords=["ကဏ္ဍ", "စီးပွား"]),
        ])
        s.commit()
        sid = src.id
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "tester", "password": "pw-for-tests"})
    c.sid = sid
    yield c
    with Session(engine()) as s:
        s.execute(delete(Source).where(Source.base_url == BASE))
        s.commit()


def test_export_requires_login():
    assert TestClient(app).get("/api/articles/export.csv").status_code == 401


def test_export_is_utf8_with_bom_and_keeps_burmese(client):
    r = client.get(f"/api/articles/export.csv?source_id={client.sid}")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    titles = [x["title"] for x in rows]
    assert "မြန်မာ စီးပွားရေး သတင်း" in titles
    my = next(x for x in rows if x["language"] == "my")
    assert my["keywords"] == "ကဏ္ဍ; စီးပွား" and my["source"] == "Export Test"


def test_export_neutralises_formula_injection(client):
    rows = list(csv.DictReader(io.StringIO(
        client.get(f"/api/articles/export.csv?source_id={client.sid}").content.decode("utf-8-sig"))))
    evil = next(x for x in rows if "HYPERLINK" in x["title"])
    assert evil["title"].startswith("'=")  # stored as text, never executed


@pytest.mark.parametrize("v,expected", [("=1+1", "'=1+1"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"),
                                        ("\tx", "'\tx"), ("normal", "normal"), (None, ""), (5, "5")])
def test_safe_cell(v, expected):
    assert safe_cell(v) == expected
