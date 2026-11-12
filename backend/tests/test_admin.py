import bcrypt
import httpx
import pytest
from fastapi.testclient import TestClient

from app import admin
from app.config import settings
from app.crawler.http import Fetcher
from app.main import app

RSS = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>'
       '<item><title>One</title><link>https://t.test/1</link><content:encoded><![CDATA[<p>'
       + "Body text of the article that is long enough to count as a real article body. " * 5
       + '</p>]]></content:encoded></item></channel></rss>')
BASE = "https://admin-test.invalid"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "tester")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"pw-for-tests", bcrypt.gensalt()).decode())

    def handler(req: httpx.Request):
        return httpx.Response(200, text=RSS) if req.url.path == "/feed" else httpx.Response(404)

    monkeypatch.setattr(admin, "Fetcher", lambda: Fetcher(
        transport=httpx.MockTransport(handler), check_public=False, default_delay=0))
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "tester", "password": "pw-for-tests"}).status_code == 200
    yield c
    for s in c.get("/api/admin/sources").json():  # clean up only what these tests created
        if s["base_url"].startswith(BASE):
            c.delete(f"/api/admin/sources/{s['id']}")


def payload(**over):
    return {"name": "Test Source", "base_url": BASE, "rss_url": f"{BASE}/feed", "method": "rss", **over}


def test_admin_requires_login():
    assert TestClient(app).get("/api/admin/sources").status_code == 401


def test_crud_roundtrip(client):
    r = client.post("/api/admin/sources", json=payload())
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.post("/api/admin/sources", json=payload()).status_code == 409  # duplicate base_url
    r = client.put(f"/api/admin/sources/{sid}", json=payload(name="Renamed", enabled=False))
    assert r.json()["name"] == "Renamed" and r.json()["enabled"] is False
    assert client.delete(f"/api/admin/sources/{sid}").status_code == 200
    assert client.put(f"/api/admin/sources/{sid}", json=payload()).status_code == 404


@pytest.mark.parametrize("bad", [
    {"base_url": "javascript:alert(1)"}, {"rss_url": "not a url"}, {"method": "scrape"},
    {"crawl_interval_minutes": 1}, {"name": ""},
])
def test_validation_rejects_bad_input(client, bad):
    assert client.post("/api/admin/sources", json=payload(**bad)).status_code == 422


def test_test_endpoint_stores_nothing_and_updates_health(client):
    sid = client.post("/api/admin/sources", json=payload()).json()["id"]
    r = client.post(f"/api/admin/sources/{sid}/test").json()
    assert r["total"] == 1 and r["method"] == "rss" and r["robots_status"] == "no_robots"
    src = next(s for s in client.get("/api/admin/sources").json() if s["id"] == sid)
    assert src["health"] == "ok" and src["article_count"] == 0


def test_crawl_runs_in_background_stores_articles_and_reports_failure(client, monkeypatch):
    monkeypatch.setattr(admin, "_spawn", lambda fn: fn())  # run the "thread" inline for determinism
    sid = client.post("/api/admin/sources", json=payload()).json()["id"]
    r = client.post(f"/api/admin/sources/{sid}/crawl")
    assert r.status_code == 202
    run = client.get(f"/api/admin/crawl-runs/{r.json()['run_id']}").json()
    assert run["status"] in ("success", "partial") and run["new"] == 1 and run["discovered"] == 1
    src = next(s for s in client.get("/api/admin/sources").json() if s["id"] == sid)
    assert src["article_count"] == 1 and src["health"] == "ok"

    bad = client.post("/api/admin/sources", json=payload(base_url=f"{BASE}/b", rss_url=f"{BASE}/missing")).json()["id"]
    run = client.get(f"/api/admin/crawl-runs/{client.post(f'/api/admin/sources/{bad}/crawl').json()['run_id']}").json()
    assert run["status"] == "failed" and run["errors"]
    runs = client.get(f"/api/admin/crawl-runs?source_id={bad}").json()
    assert runs[0]["source_name"] == "Test Source"


def test_second_crawl_of_a_running_source_is_refused(client, monkeypatch):
    monkeypatch.setattr(admin, "_spawn", lambda fn: None)  # "thread" never finishes
    sid = client.post("/api/admin/sources", json=payload()).json()["id"]
    assert client.post(f"/api/admin/sources/{sid}/crawl").status_code == 202
    assert client.post(f"/api/admin/sources/{sid}/crawl").status_code == 409
    admin._running.discard(sid)
