import shutil
import zipfile

from core.storage import StorageClient


def build_zip(
    storage: StorageClient,
    dest_path: str,
    entries: list[tuple[str, str]],
) -> list[str]:
    missing = []
    with storage.open_write(dest_path) as dest_stream:
        with zipfile.ZipFile(
            dest_stream,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as archive:
            for entry_name, source_path in entries:
                if not storage.object_exists(source_path):
                    missing.append(source_path)
                    continue
                with archive.open(entry_name, "w") as dest_file:
                    with storage.open_read(source_path) as source_file:
                        shutil.copyfileobj(
                            source_file,
                            dest_file,
                            length=1024 * 1024,
                        )
    return missing
