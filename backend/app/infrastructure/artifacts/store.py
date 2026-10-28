from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.domain.enums import ArtifactType
from backend.app.domain.local_uri import local_path_from_uri
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

    def uri_for_artifact(
        self,
        *,
        case_id: UUID,
        artifact_id: UUID,
        filename: str,
    ) -> str:
        """Return the canonical local URI bound to this artifact identity."""
        return self._artifact_path(case_id, artifact_id, filename).as_uri()

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

        generated_artifact_id = artifact_id is None
        if artifact_id is None:
            artifact_id = uuid4()

        destination = self._artifact_path(
            case_id=case_id,
            artifact_id=artifact_id,
            filename=filename,
        )

        resolved_parent = destination.parent.resolve()
        if resolved_parent != self.root and self.root not in resolved_parent.parents:
            raise ValueError("Artifact path resolves outside the configured storage root.")
        destination.parent.mkdir(parents=True, exist_ok=True)

        existing_artifact = db.get(Artifact, artifact_id)
        if existing_artifact is not None:
            raise FileExistsError(
                f"Artifact identity {artifact_id} already has a durable database record."
            )

        created_destination = False
        temporary_path: Path | None = None
        try:
            # Stage beside the destination, then publish with a hard link. Unlike
            # opening the destination with wb, link creation cannot replace an
            # artifact created by another worker or an earlier attempt.
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as staged:
                temporary_path = Path(staged.name)
                with source.open("rb") as src:
                    while chunk := src.read(8 * 1024 * 1024):
                        staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())

            staged_sha256, size_bytes = self._sha256_and_size(temporary_path)
            try:
                os.link(temporary_path, destination)
                created_destination = True
            except FileExistsError:
                if destination.is_symlink() or not destination.is_file():
                    raise FileExistsError(
                        f"Artifact storage identity {artifact_id} is not a regular file."
                    )
                existing_sha256, existing_size = self._sha256_and_size(destination)
                if (existing_sha256, existing_size) != (staged_sha256, size_bytes):
                    raise FileExistsError(
                        f"Artifact storage identity {artifact_id} already contains different bytes."
                    )

            sha256, size_bytes = self._sha256_and_size(destination)
            if sha256 != staged_sha256 or size_bytes != temporary_path.stat().st_size:
                raise RuntimeError("Published artifact bytes differ from the staged source.")

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
        except Exception:
            if generated_artifact_id and created_destination:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if generated_artifact_id:
                directory = destination.parent
                while directory != self.root:
                    try:
                        directory.rmdir()
                    except OSError:
                        break
                    directory = directory.parent

        return artifact

    def local_path(self, storage_uri: str) -> Path:
        """
        Resolve a file:// storage URI to a local filesystem path.

        Only paths contained inside this store's root are accepted.
        """
        path = local_path_from_uri(storage_uri)
        if path is None:
            raise ValueError("Artifact storage URI is not a local filesystem path.")

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
