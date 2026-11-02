"""Discover VCF specification documents from the official HTS specifications repo.

A discovered PDF is knowledge evidence, not proof that SIRALOOM implements that
specification. New versions remain CANDIDATE until a parser profile and
normative conformance suite have been implemented and qualified.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from backend.app.domain.vcf_spec_registry import BUILTIN_VCF_SPECIFICATION_VERSIONS


_REPOSITORY = "samtools/hts-specs"
_CONTENTS_URL = f"https://api.github.com/repos/{_REPOSITORY}/contents"
_OFFICIAL_INDEX = "https://samtools.github.io/hts-specs/"
_USER_AGENT = "SIRALOOM-scientific-resource-discovery/1.0"
_VCF_DOCUMENT_RE = re.compile(r"^VCFv(\d+\.\d+)\.pdf$", re.IGNORECASE)


class VCFSpecificationProvider:
    """Discover historical and newly published VCF normative specification PDFs."""

    def discover(self) -> list[dict[str, Any]]:
        response = httpx.get(
            _CONTENTS_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Official HTS specification repository returned a non-list contents payload")

        candidates = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("name") or "")
            match = _VCF_DOCUMENT_RE.fullmatch(filename)
            if not match:
                continue
            version = f"VCFv{match.group(1)}"
            if version in BUILTIN_VCF_SPECIFICATION_VERSIONS:
                continue
            document_url = f"{_OFFICIAL_INDEX}{filename}"
            candidates.append({
                "name": f"VCF specification {version}",
                "provider": "HTS-Specifications",
                "resource_type": "VCF_SPECIFICATION",
                "version": version,
                "genome_build": None,
                "access_method": "HTTPS",
                "location": None,
                "checksum": None,
                "population_definition": None,
                "metadata": {
                    "specification_version": version,
                    "official_document_url": document_url,
                    "official_index_url": _OFFICIAL_INDEX,
                    "repository": _REPOSITORY,
                    "repository_path": filename,
                    "repository_blob_sha": item.get("sha"),
                    "discovery_scope": "OFFICIAL_NORMATIVE_SPECIFICATION_DOCUMENT",
                    "qualification_required": True,
                    "parser_conformance_required": True,
                },
                "source_contract": {
                    "publisher": "Samtools HTS Specifications maintainers",
                    "canonical_source_url": f"https://github.com/{_REPOSITORY}",
                    "artifact_url": document_url,
                    "release_identity": version,
                    "access_mode": "PUBLIC",
                    "license_status": "REVIEW_REQUIRED",
                    "checksum_status": "UNKNOWN",
                    "authority_evidence_url": _OFFICIAL_INDEX,
                },
            })
        return sorted(candidates, key=lambda candidate: tuple(
            int(part) for part in str(candidate["version"]).removeprefix("VCFv").split(".")
        ))
