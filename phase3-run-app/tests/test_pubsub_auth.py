import pytest
from backend.pubsub_auth import PushAuthError, verify_push_token


def test_rejects_missing_token():
    with pytest.raises(PushAuthError):
        verify_push_token(
            authorization=None,
            expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
            verifier=lambda tok, aud: {},
        )


def test_rejects_wrong_service_account():
    def fake_verifier(token, audience):
        return {"email": "attacker@evil.com", "email_verified": True}

    with pytest.raises(PushAuthError):
        verify_push_token(
            authorization="Bearer xyz",
            expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
            verifier=fake_verifier,
        )


def test_accepts_correct_service_account():
    def fake_verifier(token, audience):
        return {"email": "of-pubsub-push@x.iam.gserviceaccount.com", "email_verified": True}

    claims = verify_push_token(
        authorization="Bearer xyz",
        expected_sa="of-pubsub-push@x.iam.gserviceaccount.com",
        verifier=fake_verifier,
    )
    assert claims["email"].startswith("of-pubsub-push@")
