import io
from typing import BinaryIO, Callable, Protocol


class _PersistingBytesIO(io.BytesIO):
    def __init__(self, persist: Callable[[bytes], None]) -> None:
        super().__init__()
        self._persist = persist

    def close(self) -> None:
        if not self.closed:
            self._persist(self.getvalue())
        super().close()


class StorageClient(Protocol):
    def object_exists(self, path: str) -> bool: ...
    def list_paths(self, prefix: str) -> list[str]: ...
    def list_objects(self, prefix: str) -> list[tuple[str, int]]: ...
    def create_exclusive(self, path: str, data: bytes) -> bool:
        """Create object only if it does not exist. True if created, False if it already existed."""
        ...
    def upload_bytes(self, path: str, data: bytes) -> None: ...
    def open_read(self, path: str) -> BinaryIO: ...
    def open_write(self, path: str) -> BinaryIO: ...
    def read_text(self, path: str) -> str: ...
    def list_case_ids(self) -> list[str]:
        """Return every case id that has an object under cases/<project>/<id>/."""
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

    def open_read(self, path: str) -> BinaryIO:
        return io.BytesIO(self._objs[path])

    def open_write(self, path: str) -> BinaryIO:
        return _PersistingBytesIO(lambda data: self._objs.__setitem__(path, data))

    def read_text(self, path: str) -> str:
        return self._objs[path].decode("utf-8")

    def list_paths(self, prefix: str) -> list[str]:
        return sorted(path for path in self._objs if path.startswith(prefix))

    def list_objects(self, prefix: str) -> list[tuple[str, int]]:
        return sorted(
            (path, len(data))
            for path, data in self._objs.items()
            if path.startswith(prefix)
        )

    def list_case_ids(self) -> list[str]:
        ids = set()
        for path in self._objs:
            parts = path.split("/")
            if len(parts) >= 4 and parts[0] == "cases" and parts[1] and parts[2]:
                ids.add(parts[2])
        return sorted(ids)

from google.cloud import storage as _gcs  # type: ignore

class GcsStorage:
    """Real StorageClient backed by google-cloud-storage. Paths are bucket-relative."""
    def __init__(self, bucket: str) -> None:
        self._bucket_name = bucket
        self._client = _gcs.Client()
        self._bucket = self._client.bucket(bucket)

    def object_exists(self, path: str) -> bool:
        return self._bucket.blob(path).exists(self._client)

    def create_exclusive(self, path: str, data: bytes) -> bool:
        blob = self._bucket.blob(path)
        try:
            blob.upload_from_string(data, if_generation_match=0)  # atomic create-only
            return True
        except Exception as e:  # google.api_core.exceptions.PreconditionFailed (412)
            if getattr(e, "code", None) == 412 or "PreconditionFailed" in type(e).__name__:
                return False
            raise

    def upload_bytes(self, path: str, data: bytes) -> None:
        self._bucket.blob(path).upload_from_string(data)

    def open_read(self, path: str) -> BinaryIO:
        return self._bucket.blob(path).open("rb")

    def open_write(self, path: str) -> BinaryIO:
        return self._bucket.blob(path).open("wb")

    def read_text(self, path: str) -> str:
        return self._bucket.blob(path).download_as_text()

    def list_paths(self, prefix: str) -> list[str]:
        return [b.name for b in self._client.list_blobs(self._bucket_name, prefix=prefix)]

    def list_objects(self, prefix: str) -> list[tuple[str, int]]:
        return [
            (blob.name, blob.size or 0)
            for blob in self._client.list_blobs(self._bucket_name, prefix=prefix)
        ]

    def list_case_ids(self) -> list[str]:
        ids = set()
        for name in self.list_paths("cases/"):
            parts = name.split("/")
            if len(parts) >= 4 and parts[0] == "cases" and parts[1] and parts[2]:
                ids.add(parts[2])
        return sorted(ids)
