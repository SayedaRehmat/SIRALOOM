from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.domain.enums import ArtifactType
from backend.app.infrastructure.db.models import Artifact


class ArtifactStore:
    """
    Local filesystem artifact store.

    Artifact files are stored under:

        <artifact_root>/<case_id>/<artifact_id>/<filename>

    The database stores a file:// URI pointing to the exact persisted file.

    This implementation is appropriate for:
      - local development
      - integration testing
      - temporary Render deployment

    It is NOT durable storage for clinical production data because
    Render free web-service filesystems are ephemeral.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """
        Prevent path traversal while preserving the supplied filename.
        """
        name = Path(filename).name.strip()

        if not name:
            raise ValueError("Artifact filename cannot be empty.")

        if name in {".", ".."}:
            raise ValueError("Invalid artifact filename.")

        return name

    def _artifact_directory(
        self,
        case_id: UUID,
        artifact_id: UUID,
    ) -> Path:
        return self.root / str(case_id) / str(artifact_id)

    def _artifact_path(
        self,
        case_id: UUID,
        artifact_id: UUID,
        filename: str,
    ) -> Path:
        safe_name = self._safe_filename(filename)
        directory = self._artifact_directory(case_id, artifact_id)
        path = directory / safe_name

        # Defensive containment check.
        if self.root not in path.parents:
            raise ValueError("Resolved artifact path escapes artifact root.")

        return path

    @staticmethod
    def _sha256_and_size(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0

        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)

        return digest.hexdigest(), size

    def put_file(
        self,
        *,
        db: Session,
        case_id: UUID,
        analysis_id: UUID | None,
        source_path: Path,
        filename: str,
        artifact_type: ArtifactType | str,
        media_type: str | None,
        genome_build: str | None,
        metadata: dict | None = None,
        specimen_id: UUID | None = None,
        paired_artifact_id: UUID | None = None,
        validation_status: str = "PENDING",
        artifact_id: UUID | None = None,
    ) -> Artifact:
        """
        Persist a source file and create its Artifact database record.

        The source file is copied rather than moved so callers retain control
        of temporary staging files.
        """
        source = Path(source_path)

        if not source.is_file():
            raise FileNotFoundError(f"Artifact source file does not exist: {source}")

        if artifact_id is None:
            artifact_id = uuid4()

        destination = self._artifact_path(
            case_id=case_id,
            artifact_id=artifact_id,
            filename=filename,
        )

        destination.parent.mkdir(parents=True, exist_ok=True)

        # Stream the copy to avoid loading potentially large VCF files into RAM.
        with source.open("rb") as src, destination.open("wb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                dst.write(chunk)

        sha256, size_bytes = self._sha256_and_size(destination)

        artifact = Artifact(
            id=artifact_id,
            analysis_id=analysis_id,
            case_id=case_id,
            artifact_type=(
                artifact_type.value
                if isinstance(artifact_type, ArtifactType)
                else str(artifact_type)
            ),
            filename=self._safe_filename(filename),
            media_type=media_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_uri=destination.as_uri(),
            genome_build=genome_build,
            specimen_id=specimen_id,
            paired_artifact_id=paired_artifact_id,
            validation_status=validation_status,
            metadata_json=dict(metadata or {}),
        )

        db.add(artifact)
        db.flush()

        return artifact

    def local_path(self, storage_uri: str) -> Path:
        """
        Resolve a file:// storage URI to a local filesystem path.

        Only paths contained inside this store's root are accepted.
        """
        if storage_uri.startswith("file://"):
            path = Path(storage_uri.removeprefix("file://")).resolve()
        else:
            path = Path(storage_uri).resolve()

        root = self.root

        if path != root and root not in path.parents:
            raise ValueError("Artifact storage URI escapes the configured artifact root.")

        return path

    def exists(self, storage_uri: str) -> bool:
        try:
            return self.local_path(storage_uri).is_file()
        except ValueError:
            return False

    def delete(self, storage_uri: str) -> None:
        path = self.local_path(storage_uri)

        if path.is_file():
            path.unlink()

    def read_bytes(self, storage_uri: str) -> bytes:
        path = self.local_path(storage_uri)

        if not path.is_file():
            raise FileNotFoundError(f"Artifact file does not exist: {path}")

        return path.read_bytes()
