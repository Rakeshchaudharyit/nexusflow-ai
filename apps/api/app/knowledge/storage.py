"""Upload storage. Local development keeps document bytes on a persistent volume
(KNOWLEDGE_UPLOAD_DIR, mounted into the api and worker containers); production would swap this
class for object storage (S3/GCS/Azure Blob) behind the same three methods.

Paths are built only from server-generated UUIDs and a validated extension, never from the
uploaded filename, and are never returned by the API.
"""

import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID


class StorageUnavailable(OSError):
    """The store could not be read or written (volume missing, disk full): transient."""


class FileStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, organization_id: UUID, document_id: UUID, version: int, extension: str):
        if not extension.startswith(".") or not extension[1:].isalnum():
            raise ValueError("invalid extension")
        return self.root / str(organization_id) / str(document_id) / f"v{version}{extension}"

    def write(
        self, organization_id: UUID, document_id: UUID, version: int, extension: str, data: bytes
    ) -> None:
        path = self._path(organization_id, document_id, version, extension)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename: a crash never leaves a partial file under the final name.
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                handle.write(data)
                temporary = handle.name
            os.replace(temporary, path)
        except OSError as error:
            raise StorageUnavailable(str(type(error).__name__)) from error

    def read(self, organization_id: UUID, document_id: UUID, version: int, extension: str):
        path = self._path(organization_id, document_id, version, extension)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as error:
            raise StorageUnavailable(str(type(error).__name__)) from error

    def prune(self, organization_id: UUID, document_id: UUID, keep_version: int) -> None:
        """Remove files of older versions of a document (best effort)."""
        folder = self.root / str(organization_id) / str(document_id)
        for path in folder.glob("v*"):
            if not path.name.startswith(f"v{keep_version}."):
                path.unlink(missing_ok=True)

    def delete_document(self, organization_id: UUID, document_id: UUID) -> None:
        shutil.rmtree(self.root / str(organization_id) / str(document_id), ignore_errors=True)
