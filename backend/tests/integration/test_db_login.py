"""Passcodes stored as SHA-256 hashes in the login_credentials table sign officers in."""
import hashlib

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import LoginCredential
from app.db.session import session_scope
from app.main import create_app


def test_database_passcode_logs_in_without_env_passcodes(fresh_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "officer_passcode", "")
    monkeypatch.setattr(s, "admin_passcode", "")
    with session_scope() as db:
        db.add(LoginCredential(role="admin", passcode_sha256=hashlib.sha256(b"open-sesame-42").hexdigest()))
    c = TestClient(create_app())
    ok = c.post("/api/auth/login", json={"name": "Sai", "passcode": "open-sesame-42"})
    assert ok.status_code == 200 and ok.json()["user"] == {"name": "Sai", "role": "admin"}
    token = ok.json()["token"]
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"]["role"] == "admin"
    assert c.post("/api/auth/login", json={"name": "Sai", "passcode": "wrong"}).status_code == 401
