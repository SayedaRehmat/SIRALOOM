from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


@pytest.mark.parametrize("version", ["VCFv4.4", "VCFv4.5"])
def test_complex_reciprocal_translocation_reconstructs_pso_event_order_and_four_bnd_orientations(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}-complex-reciprocal-translocation.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=MATEID,Number=A,Type=String,Description="ID of mate breakend">\n'
        '##INFO=<ID=EVENT,Number=A,Type=String,Description="ID of associated event">\n'
        '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "2\t321681\tbnd_W\tG\tG[13:123457[\t.\tPASS\tMATEID=bnd_X;EVENT=TRA1;EVENTTYPE=TRA:BALANCED\tGT:PSL:PSO\t0|1:.,phase:.,2\n"
        "2\t321682\tbnd_V\tT\tT]13:123456]\t.\tPASS\tMATEID=bnd_U;EVENT=TRA1;EVENTTYPE=TRA:BALANCED\tGT:PSL:PSO\t0|1:.,phase:.,3\n"
        "13\t123456\tbnd_U\tC\t[2:321682[C\t.\tPASS\tMATEID=bnd_V;EVENT=TRA1;EVENTTYPE=TRA:BALANCED\tGT:PSL:PSO\t0|1:.,phase:.,3\n"
        "13\t123457\tbnd_X\tA\t]2:321681]A\t.\tPASS\tMATEID=bnd_W;EVENT=TRA1;EVENTTYPE=TRA:BALANCED\tGT:PSL:PSO\t0|1:.,phase:.,2\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["records"] == 4
    assert len(result["breakend_adjacencies"]) == 2
    assert len(result["breakend_event_groups"]) == 1
    event_group = result["breakend_event_groups"][0]
    assert event_group["event_id"] == "TRA1"
    assert event_group["event_type"] == "TRA:BALANCED"
    assert event_group["status"] == "MATCHED"
    assert len(event_group["adjacency_ids"]) == 2
    traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
    )
    assert traversal["event_order_status"] == "RECONSTRUCTED"
    assert traversal["adjacency_status"] == "COMPLETE_FOR_OBSERVED_PAIRED_BREAKENDS"
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [2, 3]
    assert [event["event_kind"] for event in traversal["ordered_events"]] == [
        "RECIPROCAL_BREAKEND_EVENT",
        "RECIPROCAL_BREAKEND_EVENT",
    ]
    assert traversal["sequence_status"] == "UNRESOLVED_INSUFFICIENT_REFERENCE_SEGMENT_EVIDENCE"

    orientations = {
        (endpoint["alt"], endpoint["orientation"]["local_replacement"],
         endpoint["orientation"]["remote_piece_direction"],
         endpoint["orientation"]["remote_piece_reverse_complemented"],
         endpoint["orientation"]["joined_side"])
        for adjacency in result["breakend_adjacencies"]
        for endpoint in (adjacency["source"], adjacency["mate"])
    }
    assert orientations == {
        ("G[13:123457[", "G", "RIGHT", "false", "AFTER_LOCAL_REPLACEMENT"),
        ("T]13:123456]", "T", "LEFT", "true", "AFTER_LOCAL_REPLACEMENT"),
        ("[2:321682[C", "C", "RIGHT", "true", "BEFORE_LOCAL_REPLACEMENT"),
        ("]2:321681]A", "A", "LEFT", "false", "BEFORE_LOCAL_REPLACEMENT"),
    }


def test_multiallelic_mate_record_with_indistinguishable_reciprocal_alts_is_unresolved(
    tmp_path: Path,
):
    path = tmp_path / "ambiguous-multiallelic-mate-record.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##INFO=<ID=MATEID,Number=A,Type=String,Description="ID of mate breakend">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\n"
        "2\t10\tbnd2\tA\tA]1:5],C]1:5]\t.\tPASS\tMATEID=bnd1,bnd1\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BREAKEND_MATE_AMBIGUOUS"


def test_paired_breakend_without_mateid_returns_durable_unresolved_adjacency(
    tmp_path: Path,
):
    path = tmp_path / "paired-breakend-without-mateid.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,phase:.,1\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["unresolved_breakend_adjacency_count"] == 1
    unresolved = result["unresolved_breakend_adjacencies"][0]
    assert unresolved["status"] == "UNRESOLVED"
    assert unresolved["reason_code"] == "VCF_BREAKEND_MATE_ID_MISSING"
    traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
    )
    assert traversal["event_order_status"] == "RECONSTRUCTED"
    assert traversal["adjacency_status"] == "PARTIAL_OR_UNRESOLVED"
    assert "VCF_BREAKEND_MATE_ID_MISSING" in traversal["unresolved_reason_codes"]


def test_single_breakend_returns_unresolved_adjacency_without_fabricating_mate(
    tmp_path: Path,
):
    path = tmp_path / "single-breakend-unresolved-mate.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tsingle1\tA\t.A\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,phase:.,1\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["unresolved_breakend_adjacency_count"] == 1
    unresolved = result["unresolved_breakend_adjacencies"][0]
    assert unresolved["status"] == "UNRESOLVED"
    assert unresolved["reason_code"] == "VCF_DERIVATIVE_SINGLE_BREAKEND_HAS_NO_MATE"
    assert result["breakend_adjacencies"] == []
    traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
    )
    assert traversal["event_order_status"] == "RECONSTRUCTED"
    assert traversal["adjacency_status"] == "PARTIAL_OR_UNRESOLVED"
