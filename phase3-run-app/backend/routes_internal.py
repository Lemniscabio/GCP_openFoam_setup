import base64
import datetime
import json

from fastapi import APIRouter, Depends, Request, Response

from backend.deps import run_repo, settings
from backend.pubsub_auth import PushAuthError, google_verifier, verify_push_token
from core.run_repo import TERMINAL_STATES

router = APIRouter()


def push_claims(request: Request) -> dict:
    """FastAPI dependency: verify the Pub/Sub push OIDC token. Overridable in tests."""
    s = settings()
    try:
        return verify_push_token(
            authorization=request.headers.get("Authorization"),
            expected_sa=s.pubsub_push_sa,
            verifier=google_verifier,
        )
    except PushAuthError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=str(e))


@router.post("/internal/batch-events", status_code=204)
async def batch_events(
    request: Request,
    _claims=Depends(push_claims),
    runs=Depends(run_repo),
):
    envelope = await request.json()
    msg = envelope.get("message", {})
    raw = base64.b64decode(msg.get("data", "")) if msg.get("data") else b"{}"
    job = json.loads(raw or b"{}")
    name = job.get("name", "")
    batch_job_id = name.split("/")[-1] if name else msg.get("attributes", {}).get("JobUID", "")
    state = (job.get("status", {}) or {}).get("state") or msg.get("attributes", {}).get(
        "newJobState", ""
    )
    if not batch_job_id or not state:
        return Response(status_code=204)  # ack malformed messages; nothing to do
    finished = datetime.datetime.now(datetime.timezone.utc) if state in TERMINAL_STATES else None
    runs.update_state(batch_job_id, state, finished_at=finished)
    return Response(status_code=204)
