import datetime
from dataclasses import dataclass
from typing import Protocol

ROLES = {"admin", "runner", "viewer"}
STATUSES = {"pending", "active", "disabled"}


@dataclass
class UserRecord:
    email: str
    role: str | None
    status: str
    requested_at: datetime.datetime
    decided_by: str | None = None
    decided_at: datetime.datetime | None = None


def resolve_on_login(email, seed_admins, existing, now) -> UserRecord:
    """Pure: decide the user's record at login time.
    - seed admins are always ensured admin/active (idempotent)
    - brand-new users become pending
    - everyone else is returned unchanged"""
    email = email.lower()
    if email in seed_admins:
        if existing and existing.role == "admin" and existing.status == "active":
            return existing
        return UserRecord(
            email=email, role="admin", status="active",
            requested_at=(existing.requested_at if existing else now),
            decided_by="seed", decided_at=now,
        )
    if existing is None:
        return UserRecord(email=email, role=None, status="pending", requested_at=now)
    return existing


class UserRepository(Protocol):
    def get(self, email: str) -> UserRecord | None: ...
    def upsert(self, record: UserRecord) -> None: ...
    def list_all(self) -> list[UserRecord]: ...
    def set_decision(self, email: str, role: str | None, status: str,
                     decided_by: str, now: datetime.datetime) -> None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}

    def get(self, email):
        return self._users.get(email.lower())

    def upsert(self, record):
        self._users[record.email.lower()] = record

    def list_all(self):
        return sorted(self._users.values(), key=lambda u: u.email)

    def set_decision(self, email, role, status, decided_by, now):
        rec = self._users[email.lower()]
        rec.role = role
        rec.status = status
        rec.decided_by = decided_by
        rec.decided_at = now
