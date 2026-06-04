import pytest

from backend.iap import User, extract_user_from_claims


def test_extract_user():
    u = extract_user_from_claims({"email": "a@lemnisca.bio", "sub": "123"})
    assert u == User(email="a@lemnisca.bio", sub="123")


def test_missing_email_rejected():
    with pytest.raises(ValueError):
        extract_user_from_claims({"sub": "123"})
