import os
import time
import functools
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Header, HTTPException

_IAP_KEYS_URL = "https://www.gstatic.com/iap/verify/public_key"
_ISS = "https://cloud.google.com/iap"


@dataclass(frozen=True)
class User:
    email: str
    sub: str


def extract_user_from_claims(claims: dict) -> User:
    email = claims.get("email")
    if not email:
        raise ValueError("IAP JWT missing email claim")
    return User(email=email, sub=claims.get("sub", ""))


@functools.lru_cache
def _keys() -> dict:
    return httpx.get(_IAP_KEYS_URL, timeout=10).json()


def verify_iap_jwt(token: str, audience: str) -> User:
    kid = jwt.get_unverified_header(token)["kid"]
    key = _keys()[kid]
    claims = jwt.decode(
        token,
        key,
        algorithms=["ES256"],
        audience=audience,
        issuer=_ISS,
        options={"require": ["exp", "iat", "aud", "iss"]},
    )
    return extract_user_from_claims(claims)


async def current_user(x_goog_iap_jwt_assertion: str = Header(default="")) -> User:
    aud = os.environ.get("OF_IAP_AUDIENCE", "")
    if not x_goog_iap_jwt_assertion or not aud:
        if os.environ.get("OF_DEV_NO_IAP") == "1":
            return User(email="dev@lemnisca.bio", sub="dev")
        raise HTTPException(status_code=401, detail="missing IAP assertion")
    try:
        return verify_iap_jwt(x_goog_iap_jwt_assertion, aud)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid IAP JWT: {e}")
