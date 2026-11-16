"""Lossless compatibility projections for documented caller-specific VCF extensions.

The original caller artifact is never modified. A projection is created only
after caller/output-mode provenance and record-level targeted markers have been
verified by the strict VCF validator. The projection moves the DRAGEN v4.2
EVENT/EVENTTYPE values out of VCFv4.2 reserved INFO identifiers while
preserving every value and record.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Any

from backend.app.domain.vcf_validation import DRAGEN_V42_TARGETED_EXTENSION_PROFILE_ID


_ALLOWED_OUTPUT_MODES = {
    "DRAGEN_V42_HARD_FILTERED_WITH_TARGETED_MERGE",
    "DRAGEN_V42_STANDALONE_TARGETED",
}
_FIELD_RENAMES = {
    "EVENT": "DRAGEN_EVENT",
    "EVENTTYPE": "DRAGEN_EVENTTYPE",
}


class VCFCompatibilityProjectionError(ValueError):
    """Raised when a caller compatibility projection cannot be proven lossless."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_dragen_v42_event_projection(
    source_path: str | Path,
    output_path: str | Path,
    *,
    caller_semantic_attestation: dict[str, Any],
) -> dict[str, Any]:
    """Create a deterministic VCF projection with namespaced DRAGEN event fields.

    The attestation must come from validate_vcf_strict after all EVENT-bearing
    records have been checked for INFO/TARGETED. This function deliberately
    refuses header-only or filename-only claims.
    """
    source = Path(source_path)
    output = Path(output_path)
    attestation = caller_semantic_attestation
    if not isinstance(attestation, dict):
        raise VCFCompatibilityProjectionError("CALLER_SEMANTIC_ATTESTATION_REQUIRED")
    if (
        attestation.get("status") not in {
            "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
            "VERIFIED_LAB_SIGNED_RUN_MANIFEST",
        }
        or attestation.get("caller_profile_id") != "dragen_snv_germline"
        or attestation.get("caller_release") not in {"4.2", "4.2.0", "4.2.4"}
        or attestation.get("caller_extension") != "INFO/EVENT_AND_EVENTTYPE_NUMBER_A"
        or attestation.get("compatibility_profile_id") != DRAGEN_V42_TARGETED_EXTENSION_PROFILE_ID
        or attestation.get("caller_extension_detected") is not True
        or attestation.get("targeted_records_verified") is not True
        or attestation.get("output_mode") not in _ALLOWED_OUTPUT_MODES
    ):
        raise VCFCompatibilityProjectionError(
            "DRAGEN_V42_EVENT_EXTENSION_NOT_FULLY_ATTESTED"
        )
    if not source.is_file():
        raise VCFCompatibilityProjectionError("SOURCE_VCF_MISSING")
    if output.exists():
        raise FileExistsError(f"Compatibility projection already exists: {output}")

    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    if temporary.exists():
        raise FileExistsError(f"Partial compatibility projection already exists: {temporary}")

    header_definitions: set[str] = set()
    projection_records = 0
    event_records = 0
    eventtype_records = 0
    targeted_event_records = 0
    try:
        with opener(source, "rt", encoding="utf-8", newline="") as reader, temporary.open(
            "w", encoding="utf-8", newline=""
        ) as writer:
            for line_number, raw in enumerate(reader, 1):
                if raw.startswith("##fileformat="):
                    if raw.rstrip("\r\n") != "##fileformat=VCFv4.2":
                        raise VCFCompatibilityProjectionError(
                            "DRAGEN_EVENT_PROJECTION_REQUIRES_VCFv4.2"
                        )
                if raw.startswith("##INFO=<ID="):
                    field_id = raw.split("ID=", 1)[1].split(",", 1)[0]
                    if field_id in _FIELD_RENAMES:
                        if field_id in header_definitions:
                            raise VCFCompatibilityProjectionError(
                                f"DUPLICATE_SOURCE_INFO_DEFINITION:{field_id}"
                            )
                        header_definitions.add(field_id)
                        if f"Number=A" not in raw or "Type=String" not in raw:
                            raise VCFCompatibilityProjectionError(
                                f"UNEXPECTED_SOURCE_INFO_DEFINITION:{field_id}"
                            )
                        raw = raw.replace(
                            f"ID={field_id},",
                            f"ID={_FIELD_RENAMES[field_id]},",
                            1,
                        )
                    elif field_id in _FIELD_RENAMES.values():
                        raise VCFCompatibilityProjectionError(
                            f"PROJECTION_FIELD_COLLISION:{field_id}"
                        )
                if raw.startswith("#"):
                    writer.write(raw)
                    continue

                fields = raw.rstrip("\r\n").split("\t")
                if len(fields) < 8:
                    raise VCFCompatibilityProjectionError(
                        f"INVALID_RECORD_COLUMN_COUNT_AT_LINE:{line_number}"
                    )
                projection_records += 1
                info_tokens = fields[7].split(";") if fields[7] not in {"", "."} else []
                info_keys = {
                    token.partition("=")[0]
                    for token in info_tokens
                    if token
                }
                has_event = "EVENT" in info_keys
                has_eventtype = "EVENTTYPE" in info_keys
                if has_event or has_eventtype:
                    if "TARGETED" not in info_keys:
                        raise VCFCompatibilityProjectionError(
                            f"TARGETED_MARKER_MISSING_AT_LINE:{line_number}"
                        )
                    targeted_event_records += 1
                if has_event:
                    event_records += 1
                if has_eventtype:
                    eventtype_records += 1
                renamed_tokens: list[str] = []
                for token in info_tokens:
                    key, separator, value = token.partition("=")
                    replacement = _FIELD_RENAMES.get(key)
                    if replacement:
                        token = replacement + (separator + value if separator else "")
                    renamed_tokens.append(token)
                fields[7] = ";".join(renamed_tokens) if renamed_tokens else "."
                writer.write("\t".join(fields) + raw[len(raw.rstrip("\r\n")):])
            writer.flush()

        if header_definitions != set(_FIELD_RENAMES):
            raise VCFCompatibilityProjectionError(
                "SOURCE_EVENT_AND_EVENTTYPE_HEADER_DEFINITIONS_INCOMPLETE"
            )
        if event_records != targeted_event_records or eventtype_records > event_records:
            raise VCFCompatibilityProjectionError(
                "SOURCE_EVENT_RECORD_RECONCILIATION_FAILED"
            )
        temporary.replace(output)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return {
        "status": "CREATED",
        "profile_id": DRAGEN_V42_TARGETED_EXTENSION_PROFILE_ID,
        "output_mode": attestation["output_mode"],
        "source_path": str(source.resolve()),
        "source_sha256": _sha256(source),
        "projection_path": str(output.resolve()),
        "projection_sha256": _sha256(output),
        "projection_bytes": output.stat().st_size,
        "source_record_count": projection_records,
        "projection_record_count": projection_records,
        "event_record_count": event_records,
        "eventtype_record_count": eventtype_records,
        "targeted_event_record_count": targeted_event_records,
        "field_renames": dict(_FIELD_RENAMES),
        "value_preservation": "INFO_VALUES_UNCHANGED_ONLY_FIELD_IDENTIFIERS_NAMESPACED",
        "source_artifact_mutated": False,
    }
