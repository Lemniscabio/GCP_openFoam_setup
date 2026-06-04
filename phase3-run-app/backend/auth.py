import os
from dataclasses import dataclass

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token


@dataclass(frozen=True)
class User:
    email: str
    sub: str


def user_from_idinfo(idinfo: dict, allowed_domain: str) -> User:
    email = idinfo.get("email", "")
    if not idinfo.get("email_verified"):
        raise PermissionError("email not verified")

    # hd-only: require the Google Workspace 'hosted domain' claim to match.
    # Personal/non-Workspace accounts have no hd, so they're rejected outright
    # (stronger than an email-suffix match — no look-alike can slip through).
    hd = idinfo.get("hd")
    if hd != allowed_domain:
        raise PermissionError(f"not a {allowed_domain} Workspace account (hd={hd!r})")

    return User(email=email, sub=idinfo.get("sub", ""))


def _verify(token: str, audience: str) -> dict:
    return google_id_token.verify_oauth2_token(token, google_requests.Request(), audience)


async def current_user(authorization: str = Header(default="")) -> User:
    if os.environ.get("OF_DEV_NO_IAP") == "1":
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
