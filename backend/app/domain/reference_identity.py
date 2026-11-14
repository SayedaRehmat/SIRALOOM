"""Reference sequence identity primitives implementing GA4GH Refget/Seqcol v1.

This module computes content-derived identifiers from the actual FASTA sequence
stream. It intentionally does not infer sequence identity from accessions,
contig labels, or a declared manifest.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any


class ReferenceIdentityError(ValueError):
    def __init__(self, message: str, *, code: str = "REFERENCE_IDENTITY_INVALID"):
        super().__init__(message)
        self.code = code


def ga4gh_digest_bytes(canonical_bytes: bytes) -> str:
    """GA4GH digest: SHA-512, first 24 bytes, base64url, no padding."""
    digest = hashlib.sha512(canonical_bytes).digest()[:24]
    return "SQ." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _canonical_json(value: Any) -> bytes:
    # Refget Seqcol v1.0's documented Python-compatible JCS subset: keys are
    # ASCII, values contain arrays/strings/integers only, and no floats.
    return json.dumps(
        value,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    ).encode("utf-8")


def seqcol_digest(names: list[str], lengths: list[int], sequences: list[str]) -> str:
    """Compute the GA4GH Refget Sequence Collections v1.0 minimal-schema digest."""
    if not names or not (len(names) == len(lengths) == len(sequences)):
        raise ReferenceIdentityError("sequence collection arrays must be non-empty and collated")
    if any(not isinstance(n, str) or not n for n in names):
        raise ReferenceIdentityError("sequence collection names must be non-empty strings")
    if any(not isinstance(n, int) or n <= 0 for n in lengths):
        raise ReferenceIdentityError("sequence collection lengths must be positive integers")
    if len(set(names)) != len(names):
        raise ReferenceIdentityError("sequence collection names must be unique")
    attributes = {
        "lengths": lengths,
        "names": names,
        "sequences": sequences,
    }
    level_one = {
        key: ga4gh_digest_bytes(_canonical_json(value))
        for key, value in attributes.items()
    }
    # The approved minimal schema marks names and sequences as inherent.
    inherent = {"names": level_one["names"], "sequences": level_one["sequences"]}
    return ga4gh_digest_bytes(_canonical_json(inherent))


def inspect_fasta_sequence_identity(fasta_path: str | Path) -> dict[str, Any]:
    """Return per-contig length, MD5 and GA4GH Refget sequence digest.

    FASTA headers are represented by their first whitespace-delimited token,
    matching the sequence identifiers used by FAI/SAM dictionaries.
    """
    path = Path(fasta_path)
    opener = gzip.open if path.read_bytes()[:2] == b"\\x1f\\x8b" else open
    result: list[dict[str, Any]] = []
    try:
        with opener(path, "rb") as handle:
            name: str | None = None
            md5 = None
            sha512 = None
            length = 0

            def finish() -> None:
                if name is None:
                    return
                assert md5 is not None and sha512 is not None
                result.append({
                    "name": name,
                    "length": length,
                    "md5": md5.hexdigest(),
                    "ga4gh": "SQ." + base64.urlsafe_b64encode(
                        sha512.digest()[:24]
                    ).decode("ascii").rstrip("="),
                })

            for raw in handle:
                if raw.startswith(b">"):
                    finish()
                    header = raw[1:].strip().split()
                    if not header:
                        raise ReferenceIdentityError("FASTA contains an empty sequence identifier")
                    name = header[0].decode("utf-8")
                    md5 = hashlib.md5(usedforsecurity=False)
                    sha512 = hashlib.sha512()
                    length = 0
                    continue
                if name is None:
                    raise ReferenceIdentityError("FASTA sequence appears before first header")
                sequence = b"".join(raw.split()).upper()
                if not sequence:
                    continue
                if any(byte < 65 or byte > 90 for byte in sequence):
                    raise ReferenceIdentityError(f"invalid FASTA sequence character in {name}")
                md5.update(sequence)
                sha512.update(sequence)
                length += len(sequence)
            finish()
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise ReferenceIdentityError(f"cannot inspect FASTA sequence identity: {exc}") from exc
    if not result:
        raise ReferenceIdentityError("FASTA contains no sequences")
    names = [item["name"] for item in result]
    if len(names) != len(set(names)):
        raise ReferenceIdentityError("FASTA contains duplicate sequence identifiers")
    return {
        "sequences": result,
        "sequence_collection_digest": seqcol_digest(
            names,
            [item["length"] for item in result],
            [item["ga4gh"] for item in result],
        ),
    }


def validate_sequence_dictionary(
    dictionary_path: str | Path,
    sequence_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a SAM/GATK sequence dictionary against FASTA sequence identity."""
    path = Path(dictionary_path)
    if not path.is_file():
        raise ReferenceIdentityError(
            f"sequence dictionary is missing: {path}",
            code="REFERENCE_DICTIONARY_MISSING",
        )
    observed: list[dict[str, Any]] = []
    saw_header = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("@HD"):
            saw_header = True
            continue
        if not line.startswith("@SQ\\t"):
            continue
        fields: dict[str, str] = {}
        for item in line.split("\\t")[1:]:
            if ":" in item:
                key, value = item.split(":", 1)
                fields[key] = value
        try:
            name = fields["SN"]
            length = int(fields["LN"])
            md5 = fields["M5"].lower()
        except (KeyError, ValueError) as exc:
            raise ReferenceIdentityError(
                f"invalid @SQ sequence dictionary record at line {line_number}",
                code="REFERENCE_DICTIONARY_INVALID",
            ) from exc
        observed.append({"name": name, "length": length, "md5": md5})
    expected = [
        {"name": item["name"], "length": item["length"], "md5": item["md5"]}
        for item in sequence_manifest
    ]
    if not saw_header or observed != expected:
        raise ReferenceIdentityError(
            "sequence dictionary @SQ order, SN, LN, or M5 does not match the FASTA",
            code="REFERENCE_DICTIONARY_MISMATCH",
        )
    return {
        "status": "VERIFIED",
        "contig_count": len(observed),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "dictionary_version_header": True,
    }
