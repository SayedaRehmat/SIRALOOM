from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_vcf44_bnd_phase_pair(path: Path, mate_pso: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##INFO=<ID=MATEID,Number=A,Type=String,Description="ID of mate breakend">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\tGT:PSL:PSO\t0|1:phase,phase:2,3\n"
        f"2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tMATEID=bnd1\tGT:PSL:PSO\t0|1:phase,phase:2,{mate_pso}\n",
        encoding="utf-8",
    )


def test_vcf44_reciprocal_breakend_phase_vectors_must_match(tmp_path: Path):
    path = tmp_path / "vcf44-bnd-phase-mismatch.vcf"
    _write_vcf44_bnd_phase_pair(path, "4")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"


def test_vcf44_reciprocal_breakend_phase_vectors_accept_matching_values(tmp_path: Path):
    path = tmp_path / "vcf44-bnd-phase-match.vcf"
    _write_vcf44_bnd_phase_pair(path, "3")

    result = validate_vcf_strict(path)
    assert result["records"] == 2
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
    )
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [2, 3]
    assert [event["event_kind"] for event in traversal["ordered_events"]] == [
        "RECIPROCAL_BREAKEND_EVENT",
        "RECIPROCAL_BREAKEND_EVENT",
    ]
    assert [len(event["occurrences"]) for event in traversal["ordered_events"]] == [2, 2]
