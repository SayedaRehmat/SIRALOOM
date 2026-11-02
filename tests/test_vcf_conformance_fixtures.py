"""Data-driven VCF conformance fixtures pinned to official HTS specifications.

VCFv4.1-v4.5 are normative fixture targets. VCFv4.0 is a legacy parser
compatibility smoke test only because it is not listed in the current HTS
specifications index.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict


FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "vcf" / "conformance_cases.json"
)


def _load_fixture_manifest() -> dict:
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _fixture_cases() -> list[tuple[str, dict]]:
    manifest = _load_fixture_manifest()
    return [
        (version, fixture)
        for version, fixtures in manifest["versions"].items()
        for fixture in fixtures
    ]


@pytest.mark.parametrize(
    ("version", "fixture"),
    _fixture_cases(),
    ids=lambda value: value if isinstance(value, str) else value["id"],
)
def test_versioned_vcf_conformance_fixtures(
    tmp_path: Path, version: str, fixture: dict
):
    """Run each pinned fixture through the production strict validator."""
    fixture_path = tmp_path / f"{version}-{fixture['id']}.vcf"
    fixture_path.write_text("\n".join(fixture["lines"]) + "\n", encoding="utf-8")

    if fixture["expected"] == "PASS":
        result = validate_vcf_strict(fixture_path)
        assert result["fileformat"] == version
        assert result["records"] >= 1
        return

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(fixture_path)
    assert exc.value.code == fixture["expected"], (
        f"{version}/{fixture['id']} ({fixture['spec_basis']})"
    )


def test_conformance_manifest_has_normative_documents_for_maintained_versions():
    manifest = _load_fixture_manifest()
    assert set(manifest["normative_documents"]) == {
        "VCFv4.1",
        "VCFv4.2",
        "VCFv4.3",
        "VCFv4.4",
        "VCFv4.5",
    }
    for version, document in manifest["normative_documents"].items():
        assert document.endswith(f"/{version}.pdf")
    assert "legacy compatibility smoke" in manifest["legacy_compatibility_note"].lower()
