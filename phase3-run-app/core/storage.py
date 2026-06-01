from typing import Protocol

class StorageClient(Protocol):
    def object_exists(self, path: str) -> bool: ...
    def create_exclusive(self, path: str, data: bytes) -> bool:
        """Create object only if it does not exist. True if created, False if it already existed."""
        ...
    def upload_bytes(self, path: str, data: bytes) -> None: ...
    def read_text(self, path: str) -> str: ...
    def list_case_ids(self) -> list[str]:
        """Return every case id that has any object under cases/<id>/."""
        ...

class InMemoryStorage:
    """Test fake. Stores objects in a dict keyed by path."""
    def __init__(self) -> None:
        self._objs: dict[str, bytes] = {}

    def object_exists(self, path: str) -> bool:
        return path in self._objs

    def create_exclusive(self, path: str, data: bytes) -> bool:
        if path in self._objs:
            return False
        self._objs[path] = data
        return True

    def upload_bytes(self, path: str, data: bytes) -> None:
        self._objs[path] = data

    def read_text(self, path: str) -> str:
        return self._objs[path].decode("utf-8")

    def list_case_ids(self) -> list[str]:
        ids = set()
        for path in self._objs:
            if path.startswith("cases/"):
                parts = path.split("/")
                if len(parts) >= 3 and parts[1]:
                    ids.add(parts[1])
        return sorted(ids)
