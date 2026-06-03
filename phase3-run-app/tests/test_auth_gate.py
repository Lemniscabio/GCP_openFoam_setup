import importlib

from fastapi.testclient import TestClient


def test_api_requires_token(monkeypatch):
    monkeypatch.delenv("OF_DEV_NO_IAP", raising=False)
    monkeypatch.setenv("OF_OAUTH_CLIENT_ID", "test-client.apps.googleusercontent.com")

    import backend.main

    importlib.reload(backend.main)
    c = TestClient(backend.main.app)
    r = c.get("/api/cases")
    assert r.status_code == 401
    assert c.get("/healthz").status_code == 200
