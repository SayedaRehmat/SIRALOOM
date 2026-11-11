from dataclasses import dataclass
from uuid import UUID
from typing import Any
import hashlib
import json

@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: UUID
    variant_id: UUID
    evidence_type: str
    statement: str
    direction: str
    source_name: str | None
    source_version: str | None
    observation_ids: tuple[UUID, ...]
    payload: dict[str, Any]
    resource_id: UUID | None = None
    source_record_id: str | None = None
    request_fingerprint: str | None = None
    response_sha256: str | None = None
    request_metadata: dict[str, Any] | None = None
    observed_at: str | None = None
    raw_response_bytes: bytes | None = None
    response_media_type: str | None = None


def evidence_fingerprint(
    *,
    variant_id: UUID,
    analysis_id: UUID,
    evidence_type: str,
    statement: str,
    direction: str,
    source_name: str | None,
    source_version: str | None,
    observation_ids: tuple[UUID, ...],
    payload: dict[str, Any],
    resource_id: UUID | None = None,
    source_record_id: str | None = None,
    request_fingerprint: str | None = None,
    response_sha256: str | None = None,
    response_artifact_id: UUID | None = None,
    response_artifact_sha256: str | None = None,
    response_artifact_size_bytes: int | None = None,
    response_retention_status: str = "NOT_AVAILABLE",
    source_release_artifact_id: UUID | None = None,
    source_release_sha256: str | None = None,
    source_release_size_bytes: int | None = None,
    source_release_status: str = "NOT_AVAILABLE",
) -> str:
    canonical = {
        "variant_id": str(variant_id),
        "analysis_id": str(analysis_id),
        "evidence_type": evidence_type,
        "statement": statement,
        "direction": direction,
        "source_name": source_name,
        "source_version": source_version,
        "observation_ids": [str(x) for x in sorted(observation_ids, key=str)],
        "payload": payload,
        "resource_id": str(resource_id) if resource_id else None,
        "source_record_id": source_record_id,
        "request_fingerprint": request_fingerprint,
        "response_sha256": response_sha256,
        "response_artifact_id": str(response_artifact_id) if response_artifact_id else None,
        "response_artifact_sha256": response_artifact_sha256,
        "response_artifact_size_bytes": response_artifact_size_bytes,
        "response_retention_status": response_retention_status,
        "source_release_artifact_id": str(source_release_artifact_id) if source_release_artifact_id else None,
        "source_release_sha256": source_release_sha256,
        "source_release_size_bytes": source_release_size_bytes,
        "source_release_status": source_release_status,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
