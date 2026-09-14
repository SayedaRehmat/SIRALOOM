from __future__ import annotations

import hashlib
from uuid import UUID, uuid5

# Stable namespace owned by SIRALOOM. Changing this would change stable IDs.
SIRALOOM_VARIANT_NAMESPACE = UUID("7c7c3d38-5fb4-4a16-bf9a-e4dfb3c7f2d5")


def normalize_build(build: str) -> str:
    value = build.strip().lower()
    mapping = {
        "grch38": "GRCh38",
        "hg38": "GRCh38",
        "grch37": "GRCh37",
        "hg19": "GRCh37",
    }
    if value not in mapping:
        raise ValueError(f"Unsupported Phase 1 genome build: {build!r}")
    return mapping[value]


def canonical_key(build: str, chrom: str, pos: int, ref: str, alt: str) -> str:
    assembly = normalize_build(build)
    c = chrom.strip().removeprefix("chr")
    if c.upper() == "MT":
        c = "M"
    return f"{assembly}:{c}:{pos}:{ref.upper()}:{alt.upper()}"


def stable_variant_uuid(key: str) -> UUID:
    return uuid5(SIRALOOM_VARIANT_NAMESPACE, key)


def variant_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
