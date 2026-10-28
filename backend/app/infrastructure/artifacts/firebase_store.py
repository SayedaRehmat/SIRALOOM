from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.domain.enums import ArtifactType
from backend.app.infrastructure.db.models import Artifact

logger = logging.getLogger(__name__)


class FirebaseArtifactStore:
    """
    Firebase Storage / Google Cloud Storage artifact store.

    This class is intentionally initialized lazily. Importing the class does
    not initialize Firebase, which allows SIRALOOM to run with
    FIREBASE_STORAGE_ENABLED=false.

    The Firebase Admin SDK uses the configured Firebase credentials and bucket.
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        *,
        credentials_path: str | None = None,
        project_id: str | None = None,
        app_name: str | None = None,
        inherit_global_credentials: bool = True,
    ) -> None:
        self.bucket_name = bucket_name or settings.firebase_storage_bucket
        self.credentials_path = (
            credentials_path
            if credentials_path is not None
            else (settings.firebase_credentials_path if inherit_global_credentials else None)
        )
        self.project_id = project_id or settings.firebase_project_id
        self.app_name = app_name
        self.inherit_global_credentials = inherit_global_credentials

        if not self.bucket_name:
            raise RuntimeError(
                "Firebase Storage is enabled but FIREBASE_STORAGE_BUCKET "
                "is not configured."
            )

        self._bucket = None

    @property
    def bucket(self):
        if self._bucket is not None:
            return self._bucket

        app = self._initialize_firebase()

        from firebase_admin import storage

        self._bucket = storage.bucket(self.bucket_name, app=app)
        return self._bucket

    def _initialize_firebase(self):
        import firebase_admin
        from firebase_admin import credentials

        try:
            return (
                firebase_admin.get_app(self.app_name) if self.app_name else firebase_admin.get_app()
            )
        except ValueError:
            pass

        credential = None
        if self.credentials_path:
            path = Path(self.credentials_path)
            if not path.is_file():
                raise RuntimeError(f"Firebase credentials file does not exist: {path}")
            credential = credentials.Certificate(str(path))
        elif self.app_name:
            credential = credentials.ApplicationDefault()

        options = {
            key: value
            for key, value in {
                "projectId": self.project_id,
                "storageBucket": self.bucket_name,
            }.items()
            if value
        }
        try:
            if self.app_name:
                return firebase_admin.initialize_app(credential, options, name=self.app_name)
            return firebase_admin.initialize_app(credential, options)
        except ValueError:
            # Another thread in this worker may have initialized the same named
            # deployment target concurrently.
            return (
                firebase_admin.get_app(self.app_name) if self.app_name else firebase_admin.get_app()
            )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename).name.strip()

        if not name:
            raise ValueError("Artifact filename cannot be empty.")

        if name in {".", ".."}:
            raise ValueError("Invalid artifact filename.")

        return name

    @staticmethod
    def _sha256_and_size(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0

        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)

        return digest.hexdigest(), size

    @staticmethod
    def _blob_sha256_and_size(blob) -> tuple[str, int]:
        generation = getattr(blob, "generation", None)
        if generation is None:
            raise RuntimeError("Cloud artifact generation is unavailable for integrity verification.")
        digest = hashlib.sha256()
        size = 0
        with blob.open("rb", if_generation_match=generation) as remote_file:
            while chunk := remote_file.read(8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def _object_name(
        case_id: UUID,
        artifact_id: UUID,
        filename: str,
    ) -> str:
        safe_filename = FirebaseArtifactStore._safe_filename(filename)

        return (
            f"cases/{case_id}/artifacts/"
            f"{artifact_id}/{safe_filename}"
        )

    def uri_for_artifact(
        self,
        *,
        case_id: UUID,
        artifact_id: UUID,
        filename: str,
    ) -> str:
        """Return the canonical cloud URI bound to this artifact identity."""
        return f"gs://{self.bucket_name}/{self._object_name(case_id, artifact_id, filename)}"

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
        Upload a file to Firebase Storage and create its Artifact record.
        """
        source = Path(source_path)

        if not source.is_file():
            raise FileNotFoundError(
                f"Artifact source file does not exist: {source}"
            )

        generated_artifact_id = artifact_id is None
        if artifact_id is None:
            artifact_id = uuid4()

        object_name = self._object_name(
            case_id=case_id,
            artifact_id=artifact_id,
            filename=filename,
        )

        existing_artifact = db.get(Artifact, artifact_id)
        if existing_artifact is not None:
            raise FileExistsError(
                f"Artifact identity {artifact_id} already has a durable database record."
            )

        blob = self.bucket.blob(object_name)
        uploaded_generation = None
        uploaded_by_this_call = False
        try:
            sha256, size_bytes = self._sha256_and_size(source)

            if media_type:
                blob.content_type = media_type

            blob.metadata = {
                "sha256": sha256,
                "artifact_id": str(artifact_id),
                "case_id": str(case_id),
                "filename": self._safe_filename(filename),
            }

            try:
                blob.upload_from_filename(
                    str(source),
                    content_type=media_type,
                    if_generation_match=0,
                )
                uploaded_by_this_call = True
                uploaded_generation = getattr(blob, "generation", None)
            except Exception as exc:
                # A previous attempt may have created the object and lost its
                # database transaction. Reuse only an exact, verifiable orphan.
                if getattr(exc, "code", None) != 412:
                    raise
                blob.reload()
                existing_metadata = blob.metadata or {}
                if (
                    existing_metadata.get("sha256") != sha256
                    or existing_metadata.get("artifact_id") != str(artifact_id)
                    or existing_metadata.get("case_id") != str(case_id)
                    or existing_metadata.get("filename") != self._safe_filename(filename)
                    or int(blob.size or -1) != size_bytes
                ):
                    raise FileExistsError(
                        f"Cloud artifact identity {artifact_id} already contains different or unverifiable data."
                    ) from exc
                existing_sha256, existing_size = self._blob_sha256_and_size(blob)
                if (existing_sha256, existing_size) != (sha256, size_bytes):
                    raise FileExistsError(
                        f"Cloud artifact identity {artifact_id} contains bytes that fail integrity verification."
                    ) from exc
                uploaded_generation = getattr(blob, "generation", None)

            storage_uri = f"gs://{self.bucket_name}/{object_name}"

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
                storage_uri=storage_uri,
                genome_build=genome_build,
                specimen_id=specimen_id,
                paired_artifact_id=paired_artifact_id,
                validation_status=validation_status,
                metadata_json=dict(metadata or {}),
            )

            db.add(artifact)
            db.flush()
        except Exception:
            if generated_artifact_id and uploaded_by_this_call and uploaded_generation is not None:
                try:
                    blob.delete(if_generation_match=uploaded_generation)
                except Exception as cleanup_exc:  # noqa: BLE001 - preserve original operation failure
                    # Preserve the original storage/database failure.
                    logger.warning(
                        "Could not remove uncommitted cloud artifact object (%s)",
                        type(cleanup_exc).__name__,
                    )
            raise

        return artifact

    def _blob_from_uri(self, storage_uri: str):
        prefix = f"gs://{self.bucket_name}/"

        if not storage_uri.startswith(prefix):
            raise ValueError(
                "Artifact storage URI does not belong to the configured "
                "Firebase Storage bucket."
            )

        object_name = storage_uri.removeprefix(prefix)

        if not object_name:
            raise ValueError("Artifact storage URI has no object name.")

        return self.bucket.blob(object_name)

    def download_to_file(
        self,
        storage_uri: str,
        destination: Path,
        *,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> Path:
        """Download a cloud artifact directly to disk and verify its integrity."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = self._blob_from_uri(storage_uri)
        blob.download_to_filename(str(target))

        # Every artifact uploaded by this store carries its SHA-256 in object
        # metadata. Prefer an explicit caller expectation when available, but
        # otherwise verify that immutable metadata before a worker can consume
        # the downloaded file.
        metadata_sha256 = (blob.metadata or {}).get("sha256")
        verification_sha256 = expected_sha256 or metadata_sha256

        if expected_size_bytes is not None or verification_sha256 is not None:
            actual_sha256, actual_size_bytes = self._sha256_and_size(target)

            if (
                expected_size_bytes is not None
                and actual_size_bytes != expected_size_bytes
            ):
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    "Cloud artifact size mismatch: "
                    f"expected {expected_size_bytes} bytes, "
                    f"received {actual_size_bytes} bytes."
                )

            if (
                verification_sha256 is not None
                and actual_sha256.lower() != verification_sha256.lower()
            ):
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    "Cloud artifact SHA-256 mismatch: "
                    f"expected {verification_sha256}, received {actual_sha256}."
                )

        return target

    def iter_bytes(self, storage_uri: str, *, chunk_size: int = 8 * 1024 * 1024):
        """Yield bounded chunks from a cloud artifact for HTTP streaming."""
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        blob = self._blob_from_uri(storage_uri)
        with blob.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def download_bytes(self, storage_uri: str) -> bytes:
        """Convenience helper for small objects only; large files should stream."""
        blob = self._blob_from_uri(storage_uri)
        return blob.download_as_bytes()

    def exists(self, storage_uri: str) -> bool:
        try:
            blob = self._blob_from_uri(storage_uri)
            return bool(blob.exists())
        except ValueError:
            return False

    def probe(self, *, timeout_seconds: float = 5.0) -> None:
        """Verify bucket write/read/delete permissions with an isolated object.

        The object name is random and creation/deletion are generation guarded,
        so the probe cannot overwrite another object. A failed read still tries
        to remove the probe object before propagating the original failure.
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        blob = self.bucket.blob(f"_siraloom/readiness/{uuid4().hex}")
        payload = b"siraloom-storage-readiness-v1"
        generation = None
        try:
            blob.upload_from_string(
                payload,
                content_type="application/octet-stream",
                if_generation_match=0,
                timeout=timeout_seconds,
            )
            blob.reload(timeout=timeout_seconds)
            generation = blob.generation
            if generation is None:
                raise RuntimeError("Cloud storage probe did not return an object generation")
            actual = blob.download_as_bytes(
                if_generation_match=generation,
                timeout=timeout_seconds,
            )
            if actual != payload:
                raise RuntimeError("Cloud storage readiness probe content mismatch")
        except Exception:
            if generation is None:
                try:
                    blob.reload(timeout=timeout_seconds)
                    generation = blob.generation
                except Exception:  # noqa: BLE001 - preserve the original probe failure
                    generation = None
            if generation is not None:
                try:
                    blob.delete(
                        if_generation_match=generation,
                        timeout=timeout_seconds,
                    )
                except Exception as cleanup_exc:  # noqa: BLE001 - preserve original failure
                    logger.warning(
                        "Could not remove cloud storage readiness object (%s)",
                        type(cleanup_exc).__name__,
                    )
            raise
        try:
            blob.delete(if_generation_match=generation, timeout=timeout_seconds)
        except Exception as cleanup_exc:  # noqa: BLE001 - surface failed cleanup to readiness
            logger.warning(
                "Could not remove cloud storage readiness object (%s)",
                type(cleanup_exc).__name__,
            )
            raise

    def delete(self, storage_uri: str) -> None:
        blob = self._blob_from_uri(storage_uri)
        blob.delete()

    def signed_url(
        self,
        storage_uri: str,
        *,
        expiration_seconds: int = 900,
    ) -> str:
        """
        Generate a short-lived signed URL.

        This should be used instead of making clinical artifacts public.
        """
        blob = self._blob_from_uri(storage_uri)

        url = blob.generate_signed_url(
            version="v4",
            expiration=expiration_seconds,
            method="GET",
        )

        return str(url)
