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


class FirestoreUserRepository:
    COLLECTION = "of_users"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, email: str):
        return self._c.collection(self._col).document(email.lower())

    def get(self, email):
        snap = self._doc(email).get()
        if not snap.exists:
            return None
        d = snap.to_dict()
        return UserRecord(
            email=d["email"], role=d.get("role"), status=d.get("status", "pending"),
            requested_at=d.get("requested_at"), decided_by=d.get("decided_by"),
            decided_at=d.get("decided_at"),
        )

    def upsert(self, record):
        self._doc(record.email).set({
            "email": record.email.lower(), "role": record.role, "status": record.status,
            "requested_at": record.requested_at, "decided_by": record.decided_by,
            "decided_at": record.decided_at,
        }, merge=True)

    def list_all(self):
        out = []
        for snap in self._c.collection(self._col).stream():
            d = snap.to_dict()
            out.append(UserRecord(
                email=d["email"], role=d.get("role"), status=d.get("status", "pending"),
                requested_at=d.get("requested_at"), decided_by=d.get("decided_by"),
                decided_at=d.get("decided_at"),
            ))
        return sorted(out, key=lambda u: u.email)

    def set_decision(self, email, role, status, decided_by, now):
        self._doc(email).set({
            "role": role, "status": status, "decided_by": decided_by, "decided_at": now,
        }, merge=True)
