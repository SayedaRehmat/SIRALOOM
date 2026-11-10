#!/usr/bin/env python3
"""Validate the checked-in upstream source identity lock for Ensembl VEP.

This deliberately validates source identity only. It does not claim that Perl,
CPAN, BioPerl, Bio::DB::HTS, caches, or OCI images are reproducibly locked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

LOCK = Path(__file__).resolve().parents[1] / "configs/bioinformatics/profiles/vep-115.2-source.lock.json"
EXPECTED = {
    "ensembl-vep": "2beada0d57ca6234f467b14a6c60280f4a082717",
    "ensembl": "266b84da60126688c6182b7739b9c43700432cfe",
    "ensembl-io": "25061d3be5b2d65d1111fcbc01f5b871e203ad5e",
    "ensembl-variation": "23c76f60b1592e4df86159cf5530bdc326120c3d",
    "ensembl-funcgen": "57f70613f6a25d014127ec7d2bed3647af537ca7",
}


def validate_lock(document: dict) -> None:
    if document.get("schema") != "siraloom.vep-source-lock.v1":
        raise ValueError("unsupported VEP source-lock schema")
    if document.get("software_version") != "115.2" or document.get("cache_release") != "115":
        raise ValueError("VEP software version and cache release must remain distinct")
    if document.get("lock_scope") != "upstream_source_identity_only":
        raise ValueError("source identity lock must not overstate its scope")
    repos = document.get("upstream_repositories")
    if not isinstance(repos, list):
        raise ValueError("upstream_repositories must be a list")
    found = {}
    for item in repos:
        name = item.get("name")
        if name in found:
            raise ValueError(f"duplicate upstream repository: {name}")
        parsed = urlparse(item.get("url", ""))
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            raise ValueError(f"repository URL must use official GitHub HTTPS: {name}")
        commit = item.get("commit", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError(f"invalid immutable Git commit for {name}")
        found[name] = commit
    if found != EXPECTED:
        raise ValueError("upstream repository commit set differs from independently verified pins")
    if set(document.get("target_architectures", [])) != {"x86_64", "aarch64"}:
        raise ValueError("both native architectures must be explicit")
    unresolved = document.get("unresolved_lock_inputs")
    if not isinstance(unresolved, list) or len(unresolved) < 5:
        raise ValueError("incomplete environment inputs must remain explicitly disclosed")
    if document.get("qualification_status") != "CANDIDATE":
        raise ValueError("source identity pins alone cannot qualify VEP")


def main() -> int:
    validate_lock(json.loads(LOCK.read_text(encoding="utf-8")))
    print("VEP 115.2 upstream source identities: valid; environment remains CANDIDATE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
