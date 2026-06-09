import io
import zipfile

from core.archives import build_zip
from core.storage import GcsStorage, InMemoryStorage


class _FlushRaisingWriter:
    def __init__(self, persist):
        self._buffer = io.BytesIO()
        self._persist = persist

    def write(self, data):
        return self._buffer.write(data)

    def tell(self):
        return self._buffer.tell()

    def flush(self):
        raise io.UnsupportedOperation("flush")

    def close(self):
        self._persist(self._buffer.getvalue())
        self._buffer.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


class _FakeBlob:
    def __init__(self, objects, path):
        self._objects = objects
        self._path = path

    def exists(self, _client):
        return self._path in self._objects

    def open(self, mode):
        if mode == "rb":
            return io.BytesIO(self._objects[self._path])
        if mode == "wb":
            return _FlushRaisingWriter(
                lambda data: self._objects.__setitem__(self._path, data)
            )
        raise ValueError(f"unsupported mode: {mode}")


class _FakeBucket:
    def __init__(self, objects):
        self._objects = objects

    def blob(self, path):
        return _FakeBlob(self._objects, path)


def test_build_zip_streams_entries_and_collects_missing_sources():
    storage = InMemoryStorage()
    storage.upload_bytes("results/run/case_1/result.tar.gz", b"first")
    storage.upload_bytes("results/run/case_2/result.tar.gz", b"second")

    missing = build_zip(
        storage,
        "downloads/run/archive.zip",
        [
            ("case_1/result.tar.gz", "results/run/case_1/result.tar.gz"),
            ("case_2/result.tar.gz", "results/run/case_2/result.tar.gz"),
            ("case_3/result.tar.gz", "results/run/case_3/result.tar.gz"),
        ],
    )

    assert missing == ["results/run/case_3/result.tar.gz"]
    archive_bytes = storage._objs["downloads/run/archive.zip"]
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == [
            "case_1/result.tar.gz",
            "case_2/result.tar.gz",
        ]
        assert archive.read("case_1/result.tar.gz") == b"first"
        assert archive.read("case_2/result.tar.gz") == b"second"


def test_build_zip_ignores_unsupported_gcs_writer_flush():
    objects = {
        "results/run/case_1/result.tar.gz": b"first",
        "results/run/case_2/result.tar.gz": b"second",
    }
    storage = GcsStorage.__new__(GcsStorage)
    storage._client = object()
    storage._bucket = _FakeBucket(objects)

    missing = build_zip(
        storage,
        "downloads/run/archive.zip",
        [
            ("case_1/result.tar.gz", "results/run/case_1/result.tar.gz"),
            ("case_2/result.tar.gz", "results/run/case_2/result.tar.gz"),
        ],
    )

    assert missing == []
    with zipfile.ZipFile(io.BytesIO(objects["downloads/run/archive.zip"])) as archive:
        assert archive.namelist() == [
            "case_1/result.tar.gz",
            "case_2/result.tar.gz",
        ]
        assert archive.read("case_1/result.tar.gz") == b"first"
        assert archive.read("case_2/result.tar.gz") == b"second"
