import pytest

from backend.auth import User, user_from_idinfo


def test_valid_org_user():
    u = user_from_idinfo(
        {
            "email": "kartikey.attri@lemnisca.bio",
            "sub": "1",
            "email_verified": True,
            "hd": "lemnisca.bio",
        },
        allowed_domain="lemnisca.bio",
    )
    assert u == User(email="kartikey.attri@lemnisca.bio", sub="1")


def test_wrong_domain_rejected():
    with pytest.raises(PermissionError):
        user_from_idinfo(
            {"email": "x@gmail.com", "sub": "2", "email_verified": True},
            allowed_domain="lemnisca.bio",
        )


def test_unverified_email_rejected():
    with pytest.raises(PermissionError):
        user_from_idinfo(
            {"email": "x@lemnisca.bio", "sub": "3", "email_verified": False},
            allowed_domain="lemnisca.bio",
        )


def test_lemnisca_email_without_hd_rejected():
    # hd-only: a @lemnisca.bio email lacking the Workspace hd claim is rejected
    with pytest.raises(PermissionError):
        user_from_idinfo(
            {"email": "x@lemnisca.bio", "sub": "4", "email_verified": True},
            allowed_domain="lemnisca.bio",
        )
