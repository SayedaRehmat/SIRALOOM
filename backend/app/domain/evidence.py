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
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
