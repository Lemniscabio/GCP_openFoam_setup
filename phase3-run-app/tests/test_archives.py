import io
import zipfile

from core.archives import build_zip
from core.storage import InMemoryStorage


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
