"""Verification of laboratory-signed caller run manifests.

The VCF header is untrusted descriptive metadata. A signed manifest is accepted
only when its HMAC key is explicitly configured for the owning organization and
the manifest binds the exact immutable artifact bytes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.app.config import settings


REQUIRED_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "manifest_id",
    "organization_id",
    "artifact_sha256",
    "caller_profile_id",
    "caller_release",
    "pipeline_run_id",
    "assay_id",
    "reference_build",
    "issued_at",
    "signer_id",
})


class CallerAttestationError(ValueError):
    def __init__(self, message: str, *, code: str = "CALLER_ATTESTATION_INVALID"):
        super().__init__(message)
        self.code = code


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def validate_attestation_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"manifest", "key_id", "signature"}:
        raise CallerAttestationError(
            "Caller attestation must contain exactly manifest, key_id and signature."
        )
    manifest = value.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != REQUIRED_MANIFEST_FIELDS:
        raise CallerAttestationError(
            "Caller run manifest has missing or unexpected fields."
        )
    if manifest.get("schema_version") != 1:
        raise CallerAttestationError("Unsupported caller run manifest schema version.")
    for field in (
        "manifest_id", "organization_id", "artifact_sha256", "caller_profile_id",
        "caller_release", "pipeline_run_id", "assay_id", "reference_build",
        "issued_at", "signer_id",
    ):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise CallerAttestationError(f"Caller run manifest field {field} is required.")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["artifact_sha256"]):
        raise CallerAttestationError("Caller run manifest artifact_sha256 must be lowercase SHA-256.")
    if not isinstance(value.get("key_id"), str) or not value["key_id"].strip():
        raise CallerAttestationError("Caller attestation key_id is required.")
    if not isinstance(value.get("signature"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["signature"]):
        raise CallerAttestationError("Caller attestation signature must be a lowercase HMAC-SHA256 hex digest.")
    try:
        UUID(manifest["organization_id"])
    except ValueError as exc:
        raise CallerAttestationError("Caller run manifest organization_id must be a UUID.") from exc
    if manifest["reference_build"] not in {"GRCh37", "GRCh38"}:
        raise CallerAttestationError("Caller run manifest reference_build must be GRCh37 or GRCh38.")
    try:
        issued_at = datetime.fromisoformat(manifest["issued_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise CallerAttestationError("Caller run manifest issued_at must be ISO-8601.") from exc
    if issued_at.tzinfo is None:
        raise CallerAttestationError("Caller run manifest issued_at must include a timezone.")
    if issued_at > datetime.now(timezone.utc).replace(microsecond=0) + __import__("datetime").timedelta(minutes=10):
        raise CallerAttestationError("Caller run manifest issued_at is implausibly far in the future.")
    return value


def _trusted_key(organization_id: UUID, key_id: str) -> bytes:
    try:
        configured = json.loads(settings.caller_attestation_hmac_keys_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CallerAttestationError(
            "The laboratory caller-attestation trust store is not valid JSON.",
            code="CALLER_ATTESTATION_TRUST_STORE_INVALID",
        ) from exc
    organization_keys = configured.get(str(organization_id), {})
    if not isinstance(organization_keys, dict) or key_id not in organization_keys:
        raise CallerAttestationError(
            "Caller attestation signer is not trusted for this organization.",
            code="CALLER_ATTESTATION_SIGNER_UNTRUSTED",
        )
    encoded = organization_keys[key_id]
    if not isinstance(encoded, str):
        raise CallerAttestationError("Configured caller-attestation key is invalid.")
    try:
        key = bytes.fromhex(encoded)
    except ValueError as exc:
        raise CallerAttestationError("Configured caller-attestation key must be hexadecimal.") from exc
    if len(key) < 32:
        raise CallerAttestationError("Configured caller-attestation key must contain at least 32 bytes.")
    return key


def verify_signed_caller_manifest(
    path: str | Path,
    envelope: dict[str, Any],
    *,
    organization_id: UUID,
    expected_artifact_sha256: str,
) -> dict[str, Any]:
    envelope = validate_attestation_envelope(envelope)
    manifest = envelope["manifest"]
    if UUID(manifest["organization_id"]) != organization_id:
        raise CallerAttestationError(
            "Caller run manifest organization does not match the artifact tenant.",
            code="CALLER_ATTESTATION_TENANT_MISMATCH",
        )
    if manifest["artifact_sha256"] != expected_artifact_sha256:
        raise CallerAttestationError(
            "Caller run manifest digest does not match the persisted artifact identity.",
            code="CALLER_ATTESTATION_ARTIFACT_MISMATCH",
        )
    key = _trusted_key(organization_id, envelope["key_id"])
    expected_signature = hmac.new(key, canonical_manifest_bytes(manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, envelope["signature"]):
        raise CallerAttestationError(
            "Caller run manifest signature verification failed.",
            code="CALLER_ATTESTATION_SIGNATURE_INVALID",
        )

    artifact_path = Path(path)
    digest = hashlib.sha256()
    with artifact_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_artifact_sha256:
        raise CallerAttestationError(
            "Worker artifact bytes do not match the persisted artifact SHA-256.",
            code="CALLER_ATTESTATION_ARTIFACT_DIGEST_MISMATCH",
        )
    return {
        "status": "VERIFIED_LAB_SIGNED_RUN_MANIFEST",
        "schema_version": 1,
        "manifest_id": manifest["manifest_id"],
        "organization_id": manifest["organization_id"],
        "artifact_sha256": observed_sha256,
        "caller_profile_id": manifest["caller_profile_id"],
        "caller_release": manifest["caller_release"],
        "pipeline_run_id": manifest["pipeline_run_id"],
        "assay_id": manifest["assay_id"],
        "reference_build": manifest["reference_build"],
        "issued_at": manifest["issued_at"],
        "signer_id": manifest["signer_id"],
        "key_id": envelope["key_id"],
        "signature_sha256": hashlib.sha256(envelope["signature"].encode("ascii")).hexdigest(),
    }
