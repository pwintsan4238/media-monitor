import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "tester")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"pw-for-tests", bcrypt.gensalt()).decode())
    return TestClient(app)


def test_health_is_public(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_sources_requires_login(client):
    assert client.get("/api/sources").status_code == 401


def test_bad_password_rejected(client):
    assert client.post("/api/auth/login", json={"username": "tester", "password": "nope"}).status_code == 401


def test_no_hash_configured_rejects_everything(monkeypatch):
    monkeypatch.setattr(settings, "admin_password_hash", "")
    assert TestClient(app).post("/api/auth/login", json={"username": "admin", "password": ""}).status_code == 401


def test_login_then_access(client):
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pw-for-tests"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json() == {"username": "tester"}
    assert client.get("/api/sources").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/sources").status_code == 401
