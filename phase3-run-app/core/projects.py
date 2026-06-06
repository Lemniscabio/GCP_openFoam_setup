import datetime
import re
from dataclasses import dataclass
from typing import Protocol

_BAD = re.compile(r"[\x00-\x1f/]")


def is_valid_project_name(s: str) -> bool:
    if not s or len(s) > 128:
        return False
    if s in (".", ".."):
        return False
    if s != s.strip():
        return False
    return not _BAD.search(s)


@dataclass
class ProjectRecord:
    name: str
    created_by: str
    created_at: datetime.datetime


class ProjectRepository(Protocol):
    def get(self, name: str) -> ProjectRecord | None: ...

    def ensure(
        self, name: str, user: str, now: datetime.datetime
    ) -> ProjectRecord: ...

    def list_all(self) -> list[ProjectRecord]: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._p: dict[str, ProjectRecord] = {}

    def get(self, name: str) -> ProjectRecord | None:
        return self._p.get(name)

    def ensure(
        self, name: str, user: str, now: datetime.datetime
    ) -> ProjectRecord:
        if name not in self._p:
            self._p[name] = ProjectRecord(
                name=name, created_by=user, created_at=now
            )
        return self._p[name]

    def list_all(self) -> list[ProjectRecord]:
        return sorted(self._p.values(), key=lambda project: project.name)


class FirestoreProjectRepository:
    COLLECTION = "of_projects"

    def __init__(self, client, collection: str = COLLECTION) -> None:
        self._c = client
        self._col = collection

    def _doc(self, name: str):
        return self._c.collection(self._col).document(name)

    def get(self, name: str) -> ProjectRecord | None:
        snap = self._doc(name).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return ProjectRecord(
            name=data["name"],
            created_by=data.get("created_by", "unknown"),
            created_at=data.get("created_at"),
        )

    def ensure(
        self, name: str, user: str, now: datetime.datetime
    ) -> ProjectRecord:
        from google.api_core.exceptions import AlreadyExists

        try:
            self._doc(name).create(
                {"name": name, "created_by": user, "created_at": now}
            )
        except AlreadyExists:
            pass
        return self.get(name)

    def list_all(self) -> list[ProjectRecord]:
        projects = [
            self.get(snap.id)
            for snap in self._c.collection(self._col).select([]).stream()
        ]
        return sorted(
            [project for project in projects if project],
            key=lambda project: project.name,
        )
