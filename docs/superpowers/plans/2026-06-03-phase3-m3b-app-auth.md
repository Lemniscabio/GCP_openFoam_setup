# Phase 3 — M3b: App-level Google Auth (replace IAP) — Implementation Plan

> **Why this exists:** IAP's one-click managed-OAuth client is broken on the new `cfd-lemnisca` project (undocumented error 604; the OAuth-Admin-API turndown intersecting a fresh June-2026 project). The Cloud Run service + our app are verified healthy. So we drop IAP and have the **app verify a Google ID token itself**, restricted to `@lemnisca.bio`. Cloud Run stays public-ingress; the app is the gate.
>
> Tasks 1–4 are code (TDD via `codex exec`, orchestrator reviews + runs `OF_DEV_NO_IAP=1 pytest -q`). Task 0 (Console) + Task 5 (deploy) are human-run. Project = `cfd-lemnisca`.

**Goal:** Every `/api/*` request must carry `Authorization: Bearer <Google ID token>`; the backend verifies the token (signed by Google, audience = our web OAuth client, email verified, domain = `lemnisca.bio`) and rejects everything else. Static `/` + `/healthz` stay public (harmless).

**Security model:** Cloud Run `--allow-unauthenticated` (already set). Only the placeholder page + health are open. All actions (`/api/*`) require a verified org identity. No IAP dependency.

---

### Task 0 (Console, human): create a Web OAuth client ID

- [ ] Console → **Google Auth Platform → Clients → Create OAuth client** → type **Web application**, name "OpenFOAM Batch Web".
- [ ] **Authorized JavaScript origins:** `https://of-batch-app-e3slrac76q-uc.a.run.app` (and the `…380489820300.us-central1.run.app` URL too). Add `http://localhost:8080` for local dev.
- [ ] Copy the **Client ID** (`…apps.googleusercontent.com`). This is `OF_OAUTH_CLIENT_ID`.
- [ ] (Redirect URIs aren't needed — Google Identity Services uses the JS-origin token flow, not a redirect.)

---

### Task 1: config — OAuth client id + allowed domain

**Files:** Modify `core/config.py`; Test `tests/test_config.py`

- [ ] **Step 1: add to `Settings`** (after `backend_service_account`):
```python
    oauth_client_id: str = os.environ.get("OF_OAUTH_CLIENT_ID", "")
    allowed_domain: str = os.environ.get("OF_ALLOWED_DOMAIN", "lemnisca.bio")
```
- [ ] **Step 2: add a test** to `tests/test_config.py`:
```python
def test_auth_defaults():
    s = Settings()
    assert s.allowed_domain == "lemnisca.bio"
    assert s.oauth_client_id == ""   # set via env in prod
```
- [ ] **Step 3: run** `cd phase3-run-app && OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_config.py -v` → pass.
- [ ] **Step 4: commit** `git commit -m "feat(core): config for app-level Google auth (oauth_client_id, allowed_domain)"`

---

### Task 2: `backend/auth.py` — Google ID token verification

**Files:** Create `backend/auth.py`; Test `tests/test_auth.py`. (We keep `backend/iap.py` for reference but stop using it.)

- [ ] **Step 1: failing tests** (claim-checking is pure + injectable; no network)
```python
# tests/test_auth.py
import pytest
from backend.auth import User, user_from_idinfo

def test_valid_org_user():
    u = user_from_idinfo({"email": "kartikey.attri@lemnisca.bio", "sub": "1",
                          "email_verified": True, "hd": "lemnisca.bio"}, allowed_domain="lemnisca.bio")
    assert u == User(email="kartikey.attri@lemnisca.bio", sub="1")

def test_wrong_domain_rejected():
    with pytest.raises(PermissionError):
        user_from_idinfo({"email": "x@gmail.com", "sub": "2", "email_verified": True},
                         allowed_domain="lemnisca.bio")

def test_unverified_email_rejected():
    with pytest.raises(PermissionError):
        user_from_idinfo({"email": "x@lemnisca.bio", "sub": "3", "email_verified": False},
                         allowed_domain="lemnisca.bio")
```

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement `backend/auth.py`**
```python
# backend/auth.py
import os
from dataclasses import dataclass
from fastapi import Header, HTTPException
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

@dataclass(frozen=True)
class User:
    email: str
    sub: str

def user_from_idinfo(idinfo: dict, allowed_domain: str) -> "User":
    email = idinfo.get("email", "")
    if not idinfo.get("email_verified"):
        raise PermissionError("email not verified")
    # hd claim (Workspace) when present, else email domain
    domain = idinfo.get("hd") or (email.rsplit("@", 1)[-1] if "@" in email else "")
    if domain != allowed_domain:
        raise PermissionError(f"domain {domain!r} not allowed")
    return User(email=email, sub=idinfo.get("sub", ""))

def _verify(token: str, audience: str) -> dict:
    return google_id_token.verify_oauth2_token(token, google_requests.Request(), audience)

# FastAPI dependency
async def current_user(authorization: str = Header(default="")) -> "User":
    if os.environ.get("OF_DEV_NO_IAP") == "1":   # local/dev bypass (reused flag)
        return User(email="dev@lemnisca.bio", sub="dev")
    aud = os.environ.get("OF_OAUTH_CLIENT_ID", "")
    if not authorization.startswith("Bearer ") or not aud:
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        idinfo = _verify(token, aud)
        return user_from_idinfo(idinfo, os.environ.get("OF_ALLOWED_DOMAIN", "lemnisca.bio"))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")
```

- [ ] **Step 4: run → pass** `OF_DEV_NO_IAP=1 .venv/bin/pytest tests/test_auth.py -v`.

- [ ] **Step 5: commit** `git commit -m "feat(backend): Google ID token verification (org-restricted), replaces IAP"`

---

### Task 3: point routes at the new auth dependency

**Files:** Modify `backend/routes_cases.py`, `backend/routes_jobs.py`

- [ ] **Step 1:** in both route files, change the import
```python
from backend.iap import current_user, User
```
to
```python
from backend.auth import current_user, User
```
(The routes already `Depends(current_user)`, so no other change.)

- [ ] **Step 2: run full suite** `cd phase3-run-app && OF_DEV_NO_IAP=1 .venv/bin/pytest -q` → all pass (dev bypass keeps route tests green), and `.venv/bin/python -c "import backend.main; print(1)"`.

- [ ] **Step 3: commit** `git commit -m "feat(backend): routes use Google-ID-token auth dependency"`

---

### Task 4: verify the auth gate behaves (no token = 401)

**Files:** add to `tests/test_routes_jobs.py`

- [ ] **Step 1: test that without the dev bypass, a request with no token is rejected**
```python
# tests/test_auth_gate.py
import os
from fastapi.testclient import TestClient

def test_api_requires_token(monkeypatch):
    monkeypatch.delenv("OF_DEV_NO_IAP", raising=False)
    monkeypatch.setenv("OF_OAUTH_CLIENT_ID", "test-client.apps.googleusercontent.com")
    # import app fresh so the dependency sees env without the dev bypass
    import importlib, backend.main
    importlib.reload(backend.main)
    c = TestClient(backend.main.app)
    r = c.get("/api/cases")
    assert r.status_code == 401
    # health + root stay open
    assert c.get("/healthz").status_code == 200
```

- [ ] **Step 2: run** `.venv/bin/pytest tests/test_auth_gate.py -v` → pass. Then restore full suite: `OF_DEV_NO_IAP=1 .venv/bin/pytest -q`.

- [ ] **Step 3: commit** `git commit -m "test(backend): /api requires org token; health/root stay open"`

---

### Task 5 (RUNBOOK, human): redeploy with auth env + confirm IAP off

Single-line. Project `cfd-lemnisca`.

- [ ] **Step 1: build + push the updated backend image**
```
docker buildx build --platform linux/amd64 -f phase3-run-app/backend/Dockerfile -t us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.2.0 --push phase3-run-app
```
- [ ] **Step 2: deploy public + set the OAuth client id** (replace CLIENT_ID with Task 0's value)
```
gcloud run deploy of-batch-app --image us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/of-backend:0.2.0 --region us-central1 --service-account of-batch-backend@cfd-lemnisca.iam.gserviceaccount.com --allow-unauthenticated --update-env-vars OF_OAUTH_CLIENT_ID=CLIENT_ID,OF_ALLOWED_DOMAIN=lemnisca.bio --project cfd-lemnisca
```
- [ ] **Step 3: confirm IAP stays OFF** (we're not using it) — IAP toggle off in Console (already done).
- [ ] **Step 4: verify** — `curl https://…run.app/healthz` → `{"ok":true}` (open). `curl https://…run.app/api/cases` → **401** (no token). The real end-to-end (signed-in user calling `/api`) is exercised by the M4 frontend.

---

## Notes / hand-off to M4
- The frontend (M4) integrates **Google Identity Services** (`https://accounts.google.com/gsi/client`) with `client_id = OF_OAUTH_CLIENT_ID`, gets an **ID token**, and sends it as `Authorization: Bearer <token>` on every `/api/*` call. Sign-in button gates the SPA.
- `backend/iap.py` is retained but unused (could be deleted later, or kept if IAP is ever fixed).
- If IAP later starts working (support case), we can switch back by re-pointing the dependency — the route layer is unchanged either way.

## Self-Review
- Replaces broken IAP with app-verified Google ID tokens, org-restricted → Tasks 1–4. ✓
- Public ingress but `/api/*` gated (401 w/o token, 403 wrong domain), health/root open → Task 4 test. ✓
- Deploy sets `OF_OAUTH_CLIENT_ID` + `OF_ALLOWED_DOMAIN` → Task 5. ✓
- Token verification uses official `google.oauth2.id_token.verify_oauth2_token` (no hand-rolled crypto). ✓
- Dev bypass (`OF_DEV_NO_IAP=1`) reused so existing route tests stay green. ✓
