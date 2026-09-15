from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.domain.enums import ArtifactType
from backend.app.infrastructure.db.models import Artifact


class FirebaseArtifactStore:
    """
    Firebase Storage / Google Cloud Storage artifact store.

    This class is intentionally initialized lazily. Importing the class does
    not initialize Firebase, which allows SIRALOOM to run with
    FIREBASE_STORAGE_ENABLED=false.

    The Firebase Admin SDK uses the configured Firebase credentials and bucket.
    """

    def __init__(self, bucket_name: str | None = None) -> None:
        self.bucket_name = bucket_name or settings.firebase_storage_bucket

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

        self._initialize_firebase()

        from firebase_admin import storage

        self._bucket = storage.bucket(self.bucket_name)
        return self._bucket

    @staticmethod
    def _initialize_firebase() -> None:
        import firebase_admin
        from firebase_admin import credentials

        try:
            firebase_admin.get_app()
            return
        except ValueError:
            pass

        credentials_path = settings.firebase_credentials_path

        if credentials_path:
            path = Path(credentials_path)

            if not path.is_file():
                raise RuntimeError(
                    f"Firebase credentials file does not exist: {path}"
                )

            cred = credentials.Certificate(str(path))

            firebase_admin.initialize_app(
                cred,
                {
                    "projectId": settings.firebase_project_id,
                    "storageBucket": settings.firebase_storage_bucket,
                },
            )
            return

        # Fall back to Application Default Credentials.
        firebase_admin.initialize_app(
            options={
                "projectId": settings.firebase_project_id,
                "storageBucket": settings.firebase_storage_bucket,
            }
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

        if artifact_id is None:
            artifact_id = uuid4()

        object_name = self._object_name(
            case_id=case_id,
            artifact_id=artifact_id,
            filename=filename,
        )

        sha256, size_bytes = self._sha256_and_size(source)

        blob = self.bucket.blob(object_name)

        if media_type:
            blob.content_type = media_type

        blob.metadata = {
            "sha256": sha256,
            "artifact_id": str(artifact_id),
            "case_id": str(case_id),
            "filename": self._safe_filename(filename),
        }

        blob.upload_from_filename(
            str(source),
            content_type=media_type,
        )

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

    def download_bytes(self, storage_uri: str) -> bytes:
        blob = self._blob_from_uri(storage_uri)
        return blob.download_as_bytes()

    def exists(self, storage_uri: str) -> bool:
        try:
            blob = self._blob_from_uri(storage_uri)
            return bool(blob.exists())
        except ValueError:
            return False

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
