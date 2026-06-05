import datetime

import pytest
from fastapi import HTTPException

from backend.rbac import _enforce  # pure helper exercised directly
from core.users import UserRecord

NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _rec(role, status="active"):
    return UserRecord(email="u@lemnisca.bio", role=role, status=status, requested_at=NOW)


def test_active_required():
    with pytest.raises(HTTPException) as e:
        _enforce(_rec("runner", status="pending"), need="active")
    assert e.value.status_code == 403


def test_runner_allows_runner_and_admin():
    _enforce(_rec("runner"), need="runner")
    _enforce(_rec("admin"), need="runner")
    with pytest.raises(HTTPException):
        _enforce(_rec("viewer"), need="runner")


def test_admin_only():
    _enforce(_rec("admin"), need="admin")
    with pytest.raises(HTTPException):
        _enforce(_rec("runner"), need="admin")


def test_active_allows_any_active_role():
    for r in ("admin", "runner", "viewer"):
        _enforce(_rec(r), need="active")
