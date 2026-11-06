from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "diagnose_giab_spanning_deletions.py"
SPEC = importlib.util.spec_from_file_location("diagnose_giab_spanning_deletions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_vcf(path: Path, records: str, *, contig: str = "3") -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        f"##contig=<ID={contig},length=198295559>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG001\n"
        + records,
        encoding="utf-8",
    )


def test_context_capture_records_orphan_star_without_weakening_validator(tmp_path):
    path = tmp_path / "orphan.vcf"
    _write_vcf(path, "3\t30804994\tstar\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n")

    result = MODULE.collect_context(path, "GRCh37")

    assert result["target_record"]["position"] == 30_804_994
    assert result["target_record"]["alt"] == "*,G"
    assert result["target_star_carrier_sample_indexes"] == [0]
    assert result["overlapping_deletion_candidate_count"] == 0
    assert result["same_sample_deletion_context_found"] is False
    assert result["same_sample_deletion_context_indeterminate"] is False


def test_official_hg001_orphan_mixed_star_records_remain_fail_closed_for_both_builds(tmp_path):
    from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict

    cases = (
        ("GRCh37", "3", 30_804_994),
        ("GRCh38", "chr3", 30_763_502),
    )
    for build, contig, position in cases:
        path = tmp_path / f"{build}.vcf"
        _write_vcf(
            path,
            f"{contig}\t{position}\t.\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n",
            contig=contig,
        )

        diagnostic = MODULE.diagnose(path, build, MODULE.md5_file(path))

        assert diagnostic["production_validator"]["status"] == "REJECTED"
        assert diagnostic["production_validator"]["error_code"] == (
            "VCF_SPANNING_DELETION_CONTEXT_MISSING"
        )
        assert diagnostic["context"]["overlapping_deletion_candidate_count"] == 0
        assert diagnostic["context"]["same_sample_deletion_context_found"] is False
        assert diagnostic["context"]["same_sample_deletion_context_indeterminate"] is False
        record = diagnostic["context"]["target_record"]
        assert (record["contig"], record["position"], record["ref"], record["alt"]) == (
            contig,
            position,
            "GGCGGC",
            "*,G",
        )
        assert record["genotypes"] == [{"sample_index": 0, "GT": "1/2"}]
        with pytest.raises(StrictVCFValidationError) as exc:
            validate_vcf_strict(path)
        assert exc.value.code == "VCF_SPANNING_DELETION_CONTEXT_MISSING"


def test_mixed_star_allele_not_carried_does_not_require_deletion_context(tmp_path):
    from backend.app.domain.vcf_validation import validate_vcf_strict

    path = tmp_path / "uncarried-mixed-star.vcf"
    _write_vcf(path, "3\t30804994\t.\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t0/2\n")

    diagnostic = MODULE.collect_context(path, "GRCh37")
    profile = validate_vcf_strict(path)

    assert diagnostic["target_star_carrier_sample_indexes"] == []
    assert diagnostic["target_record"]["alt"] == "*,G"
    assert diagnostic["target_record"]["genotypes"] == [{"sample_index": 0, "GT": "0/2"}]
    assert profile["records"] == 1


def test_context_capture_identifies_same_sample_deletion_context(tmp_path):
    path = tmp_path / "contextual.vcf"
    _write_vcf(
        path,
        "3\t30804993\tdel\tAGGCGGC\tA\t.\tPASS\t.\tGT\t0/1\n"
        "3\t30804994\tstar\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n",
    )

    result = MODULE.collect_context(path, "GRCh37")

    assert result["overlapping_deletion_candidate_count"] == 1
    assert result["candidate_carrier_matches"] == [True]
    assert result["same_sample_deletion_context_found"] is True
    assert result["same_sample_deletion_context_indeterminate"] is False
