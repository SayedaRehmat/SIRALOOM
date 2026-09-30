"""Governance contract for externally sourced scientific resources.

Discovery providers must identify the authoritative publisher, the exact
artifact endpoint, release identity, access mode, and licensing/terms status.
This contract does not grant permission and does not claim that a URL is
authentic merely because it is syntactically valid; provider-specific evidence
must be reviewed and qualified before activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class ResourceSourceContractError(ValueError):
    pass


_ALLOWED_ACCESS = frozenset({"PUBLIC", "AUTHENTICATED", "LICENSE_REQUIRED", "LOCAL_ONLY"})
_ALLOWED_LICENSE = frozenset({"VERIFIED", "NOT_REQUIRED", "REVIEW_REQUIRED", "RESTRICTED", "UNKNOWN"})
_ALLOWED_CHECKSUM = frozenset({"PUBLISHED_AND_VERIFIED", "TRANSPORT_DIGEST_ONLY", "NOT_PUBLISHED", "UNKNOWN"})


@dataclass(frozen=True)
class ResourceSourceContract:
    publisher: str
    canonical_source_url: str
    artifact_url: str
    release_identity: str
    access_mode: str
    license_status: str
    license_url: str | None
    terms_url: str | None
    checksum_status: str
    authority_evidence_url: str

    def as_dict(self) -> dict[str, object]:
        return {
            "publisher": self.publisher,
            "canonical_source_url": self.canonical_source_url,
            "artifact_url": self.artifact_url,
            "release_identity": self.release_identity,
            "access_mode": self.access_mode,
            "license_status": self.license_status,
            "license_url": self.license_url,
            "terms_url": self.terms_url,
            "checksum_status": self.checksum_status,
            "authority_evidence_url": self.authority_evidence_url,
        }


def _require_https_url(value: str, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ResourceSourceContractError(f"{field} must be an absolute HTTPS URL")
    return value


def validate_source_contract(value: dict[str, object]) -> ResourceSourceContract:
    if not isinstance(value, dict):
        raise ResourceSourceContractError("source_contract must be an object")

    required = (
        "publisher", "canonical_source_url", "artifact_url", "release_identity",
        "access_mode", "license_status", "checksum_status", "authority_evidence_url",
    )
    missing = [key for key in required if not str(value.get(key) or "").strip()]
    if missing:
        raise ResourceSourceContractError(
            "source_contract missing required fields: " + ", ".join(missing)
        )

    access_mode = str(value["access_mode"]).upper()
    license_status = str(value["license_status"]).upper()
    checksum_status = str(value["checksum_status"]).upper()
    if access_mode not in _ALLOWED_ACCESS:
        raise ResourceSourceContractError(f"unsupported access_mode {access_mode!r}")
    if license_status not in _ALLOWED_LICENSE:
        raise ResourceSourceContractError(f"unsupported license_status {license_status!r}")
    if checksum_status not in _ALLOWED_CHECKSUM:
        raise ResourceSourceContractError(f"unsupported checksum_status {checksum_status!r}")

    contract = ResourceSourceContract(
        publisher=str(value["publisher"]).strip(),
        canonical_source_url=_require_https_url(str(value["canonical_source_url"]), "canonical_source_url"),
        artifact_url=_require_https_url(str(value["artifact_url"]), "artifact_url"),
        release_identity=str(value["release_identity"]).strip(),
        access_mode=access_mode,
        license_status=license_status,
        license_url=_require_https_url(str(value["license_url"]), "license_url") if value.get("license_url") else None,
        terms_url=_require_https_url(str(value["terms_url"]), "terms_url") if value.get("terms_url") else None,
        checksum_status=checksum_status,
        authority_evidence_url=_require_https_url(
            str(value["authority_evidence_url"]), "authority_evidence_url"
        ),
    )

    if contract.license_status == "VERIFIED" and not (contract.license_url or contract.terms_url):
        raise ResourceSourceContractError(
            "verified license status requires a license_url or terms_url"
        )
    if contract.access_mode == "LICENSE_REQUIRED" and contract.license_status != "VERIFIED":
        raise ResourceSourceContractError(
            "LICENSE_REQUIRED resources require a verified license before qualification"
        )
    return contract
