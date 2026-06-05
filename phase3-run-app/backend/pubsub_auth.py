"""Verify the OIDC token Pub/Sub attaches to push requests.

The verifier is injected so unit tests stay offline; production passes a verifier
backed by google.oauth2.id_token.verify_oauth2_token.
"""


class PushAuthError(Exception):
    pass


def verify_push_token(authorization: str | None, expected_sa: str, verifier) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise PushAuthError("missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = verifier(token, None)
    except Exception as e:  # noqa: BLE001
        raise PushAuthError(f"invalid token: {e}") from e
    if claims.get("email") != expected_sa or not claims.get("email_verified", False):
        raise PushAuthError("token not from the expected push service account")
    return claims


def google_verifier(token: str, audience):
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, g_requests.Request(), audience)
