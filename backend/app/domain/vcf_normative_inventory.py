"""Reproducible extraction of normative-language candidates from official VCF specs.

This is an inventory aid, not a conformance verdict. Every extracted candidate
requires human clause review and explicit code/test traceability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

HTS_SPECS_REPOSITORY = "samtools/hts-specs"
HTS_SPECS_COMMIT = "510c107ba89aa13113818c9e4fa3071283cb7f7b"
HTS_SPECS_COMMIT_SIGNATURE_VERIFIED = True

SPEC_BLOB_SHA1 = {
    "VCFv4.1": "420cee83a66259600a70de36721763cc374df1e3",
    "VCFv4.2": "70e595cdad351b3fb12e121850d7e6c8c5f67c88",
    "VCFv4.3": "01671b89e21fc1bca414b639a4ea483194f127a9",
    "VCFv4.4": "31cb66283ea40c3df51e488c5fffe826fd8dedaf",
    "VCFv4.5": "307950e7eeafc33d524969ff906343f756adb7d7",
}

SPEC_EXPECTED_CANDIDATE_LINES = {
    "VCFv4.1": 60,
    "VCFv4.2": 66,
    "VCFv4.3": 119,
    "VCFv4.4": 205,
    "VCFv4.5": 230,
}

_HEADING = re.compile(r"^\\(section|subsection|subsubsection|paragraph)\{(.*)\}")
_NORMATIVE = re.compile(
    r"\b(must\s+not|shall\s+not|should\s+not|must|shall|should|"
    r"required|recommended|optional|may)\b",
    re.IGNORECASE,
)
_HEADING_LEVEL = {
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
}


def git_blob_sha1(content: bytes) -> str:
    """Return the canonical Git blob object SHA-1 for exact source verification."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def extract_vcf_normative_candidates(
    source_dir: Path,
    *,
    expected_blob_shas: Mapping[str, str] | None = SPEC_BLOB_SHA1,
    expected_candidate_lines: Mapping[str, int] | None = SPEC_EXPECTED_CANDIDATE_LINES,
) -> dict:
    """Extract line-level normative-language candidates from pinned VCF sources."""
    versions: dict[str, dict] = {}
    for version, expected_blob_sha in SPEC_BLOB_SHA1.items():
        source_path = source_dir / f"{version}.tex"
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing official VCF source file: {source_path}")

        raw = source_path.read_bytes()
        actual_blob_sha = git_blob_sha1(raw)
        if expected_blob_shas is not None:
            expected = expected_blob_shas.get(version)
            if expected is None or actual_blob_sha != expected:
                raise ValueError(
                    f"Official source blob mismatch for {version}: "
                    f"expected={expected!r}, actual={actual_blob_sha}"
                )

        lines = raw.decode("utf-8").splitlines()
        heading_stack: list[tuple[int, str, int]] = []
        candidates: list[dict] = []
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue

            heading = _HEADING.match(stripped)
            if heading:
                level = _HEADING_LEVEL[heading.group(1)]
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, heading.group(2).strip(), line_number))

            matches = [match.group(0).lower() for match in _NORMATIVE.finditer(line)]
            if not matches:
                continue

            candidates.append(
                {
                    "candidate_id": f"{version}:L{line_number:04d}",
                    "source_line": line_number,
                    "source_line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
                    "section_path": [
                        {"level": level, "heading": title, "heading_line": heading_line}
                        for level, title, heading_line in heading_stack
                    ],
                    "normative_terms": matches,
                    "candidate_kind": "NORMATIVE_LANGUAGE_LINE",
                    "review_status": "UNREVIEWED",
                    "traceability_status": "UNMAPPED",
                    "code_symbols": [],
                    "test_ids": [],
                }
            )

        expected_count = expected_candidate_lines.get(version) if expected_candidate_lines is not None else None
        if expected_count is not None and len(candidates) != expected_count:
            raise ValueError(
                f"Normative candidate count changed for {version}: "
                f"expected={expected_count}, actual={len(candidates)}"
            )

        versions[version] = {
            "source_file": source_path.name,
            "source_blob_sha1": actual_blob_sha,
            "source_line_count": len(lines),
            "candidate_line_count": len(candidates),
            "candidates": candidates,
        }

    return {
        "schema_version": "1.0",
        "inventory_kind": "NORMATIVE_LANGUAGE_CANDIDATES_NOT_REVIEWED_CLAUSES",
        "source_repository": HTS_SPECS_REPOSITORY,
        "source_commit_sha": HTS_SPECS_COMMIT,
        "source_commit_signature_verified_by_github": HTS_SPECS_COMMIT_SIGNATURE_VERIFIED,
        "inventory_status": "EXTRACTED_UNREVIEWED",
        "qualification_status": "BLOCKED_PENDING_CLAUSE_REVIEW_AND_TRACEABILITY",
        "extraction_method": (
            "Line-level extraction of normative modal language; candidate lines "
            "are not assumed to equal complete normative clauses."
        ),
        "versions": versions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = extract_vcf_normative_candidates(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
