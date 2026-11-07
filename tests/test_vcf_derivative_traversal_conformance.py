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
    assert traversal["adjacency_status"] == "COMPLETE_FOR_OBSERVED_BREAKEND_RELATIONSHIPS"
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


@pytest.mark.parametrize(
    "version", ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"]
)
def test_reciprocal_bnd_event_group_and_orientation_are_supported_across_versions(
    tmp_path: Path, version: str
):
    legacy_cardinality = version in {"VCFv4.1", "VCFv4.2", "VCFv4.3"}
    mate_number = "." if legacy_cardinality else "A"
    event_number = "1" if legacy_cardinality else "A"
    path = tmp_path / f"{version}-reciprocal-bnd-event.vcf"
    header = (
        f"##fileformat={version}\n"
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">\n'
        f'##INFO=<ID=MATEID,Number={mate_number},Type=String,Description="ID of mate breakend">\n'
        f'##INFO=<ID=EVENT,Number={event_number},Type=String,Description="ID of associated event">\n'
    )
    event_type = ""
    if not legacy_cardinality:
        header += '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">\n'
        event_type = ";EVENTTYPE=TRA:BALANCED"
    header += "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    path.write_text(
        header
        + f"1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2;EVENT=E1{event_type}\n"
        + f"2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1;EVENT=E1{event_type}\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["breakend_records"] == 2
    assert len(result["breakend_adjacencies"]) == 1
    assert result["breakend_adjacencies"][0]["event_group_status"] == "MATCHED"
    assert result["breakend_adjacencies"][0]["source"]["orientation"]["remote_piece_direction"] == "LEFT"
    assert result["breakend_adjacencies"][0]["mate"]["orientation"]["remote_piece_direction"] == "LEFT"
    assert result["breakend_event_groups"][0]["event_id"] == "E1"
    assert result["breakend_event_groups"][0]["status"] == "MATCHED"
    assert result["unresolved_breakend_adjacency_count"] == 0


@pytest.mark.parametrize(
    "version", ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"]
)
def test_multiple_alt_breakend_mates_are_resolved_by_alt_index_across_versions(
    tmp_path: Path, version: str
):
    legacy_cardinality = version in {"VCFv4.1", "VCFv4.2", "VCFv4.3"}
    mate_number = "." if legacy_cardinality else "A"
    event_number = "1" if legacy_cardinality else "A"
    path = tmp_path / f"{version}-multi-alt-bnd-mates.vcf"
    if legacy_cardinality:
        event_values = ("E1", "E1", "E1")
    else:
        event_values = ("E1,E2", "E1", "E2")
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">\n'
        f'##INFO=<ID=MATEID,Number={mate_number},Type=String,Description="ID of mate breakend">\n'
        f'##INFO=<ID=EVENT,Number={event_number},Type=String,Description="ID of associated event">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t5\tbndU\tA\tA]2:10],A]3:20]\t.\tPASS\tSVTYPE=BND;MATEID=bndV,bndZ;EVENT={event_values[0]}\n"
        f"2\t10\tbndV\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU;EVENT={event_values[1]}\n"
        f"3\t20\tbndZ\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU;EVENT={event_values[2]}\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["records"] == 3
    assert len(result["breakend_adjacencies"]) == 2
    assert {
        item["source"]["alt_index"] for item in result["breakend_adjacencies"]
    } == {1, 2}
    if legacy_cardinality:
        assert {item["event_id"] for item in result["breakend_adjacencies"]} == {"E1"}
        assert len(result["breakend_event_groups"]) == 1
    else:
        assert {item["event_id"] for item in result["breakend_adjacencies"]} == {"E1", "E2"}
        assert len(result["breakend_event_groups"]) == 2


@pytest.mark.parametrize(
    "version", ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"]
)
@pytest.mark.parametrize("alt", [".A", "A."])
def test_single_breakend_is_preserved_as_unresolved_without_mate_across_versions(
    tmp_path: Path, version: str, alt: str
):
    path = tmp_path / f"{version}-single-breakend.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t5\tsingle1\tA\t{alt}\t.\tPASS\tSVTYPE=BND\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["unresolved_breakend_adjacency_count"] == 1
    assert result["unresolved_breakend_adjacencies"][0]["reason_code"] == (
        "VCF_DERIVATIVE_SINGLE_BREAKEND_HAS_NO_MATE"
    )
    assert result["breakend_adjacencies"] == []


@pytest.mark.parametrize(
    "version", ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"]
)
def test_parid_partner_edges_are_distinct_from_mate_adjacencies_across_versions(
    tmp_path: Path, version: str
):
    legacy_cardinality = version in {"VCFv4.1", "VCFv4.2", "VCFv4.3"}
    mate_number = "." if legacy_cardinality else "A"
    partner_number = "1" if legacy_cardinality else "A"
    event_number = "1" if legacy_cardinality else "A"
    path = tmp_path / f"{version}-parid-partner-graph.vcf"
    header = (
        f"##fileformat={version}\n"
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">\n'
        f'##INFO=<ID=MATEID,Number={mate_number},Type=String,Description="ID of mate breakend">\n'
        f'##INFO=<ID=PARID,Number={partner_number},Type=String,Description="ID of partner breakend">\n'
        f'##INFO=<ID=EVENT,Number={event_number},Type=String,Description="ID of associated event">\n'
    )
    if version in {"VCFv4.4", "VCFv4.5"}:
        header += (
            '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">\n'
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
            '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
            '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        )
        sample_v = "\tGT:PSL:PSO\t0|1:.,phase:.,2"
        sample_u = "\tGT:PSL:PSO\t0|1:.,phase:.,2"
        sample_x = "\tGT:PSL:PSO\t0|1:.,phase:.,3"
        sample_y = "\tGT:PSL:PSO\t0|1:.,phase:.,3"
    else:
        header += "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        sample_v = sample_u = sample_x = sample_y = ""

    common = ";EVENT=TRA1"
    event_type = ";EVENTTYPE=TRA:BALANCED" if not legacy_cardinality else ""
    path.write_text(
        header
        + "2\t321681\tbndX\tG\tG[13:123457[\t.\tPASS\tSVTYPE=BND;MATEID=bndY;PARID=bndV"
        + common + event_type + sample_x + "\n"
        + "2\t321682\tbndV\tT\tT]13:123456]\t.\tPASS\tSVTYPE=BND;MATEID=bndU;PARID=bndX"
        + common + event_type + sample_v + "\n"
        + "13\t123456\tbndU\tC\tC[2:321682[\t.\tPASS\tSVTYPE=BND;MATEID=bndV;PARID=bndY"
        + common + event_type + sample_u + "\n"
        + "13\t123457\tbndY\tA\t]2:321681]A\t.\tPASS\tSVTYPE=BND;MATEID=bndX;PARID=bndU"
        + common + event_type + sample_y + "\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert len(result["breakend_adjacencies"]) == 2
    assert len(result["breakend_partner_links"]) == 2
    assert len(result["unresolved_breakend_partner_links"]) == 0
    event_group = result["breakend_event_groups"][0]
    assert event_group["event_id"] == "TRA1"
    assert len(event_group["adjacency_ids"]) == 2
    assert len(event_group["partner_link_ids"]) == 2

    if version in {"VCFv4.4", "VCFv4.5"}:
        traversal = next(
            item for item in result["derivative_chromosome_traversals"]
            if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
        )
        assert traversal["event_order_status"] == "RECONSTRUCTED"
        assert traversal["adjacency_status"] == "COMPLETE_FOR_OBSERVED_BREAKEND_RELATIONSHIPS"
        assert traversal["derivative_graph_status"] == "CONNECTED_MATEID_PARID_GRAPH"
        assert len(traversal["derivative_graph_nodes"]) == 4
        assert len(traversal["derivative_graph_edges"]) == 4
        assert len(traversal["derivative_graph_components"]) == 1
        assert traversal["sequence_status"] == "UNRESOLVED_INSUFFICIENT_REFERENCE_SEGMENT_EVIDENCE"


def test_nonreciprocal_parid_is_preserved_as_unresolved_partner_evidence(
    tmp_path: Path,
):
    path = tmp_path / "nonreciprocal-parid.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">\n'
        '##INFO=<ID=MATEID,Number=A,Type=String,Description="ID of mate breakend">\n'
        '##INFO=<ID=PARID,Number=A,Type=String,Description="ID of partner breakend">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2;PARID=bnd3\tGT:PSL:PSO\t0|1:.,phase:.,2\n"
        "1\t6\tbnd3\tA\tA]3:20]\t.\tPASS\tSVTYPE=BND;MATEID=bnd4\tGT:PSL:PSO\t0|1:.,phase:.,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:.,phase:.,2\n"
        "3\t20\tbnd4\tA\tA]1:6]\t.\tPASS\tSVTYPE=BND;MATEID=bnd3\tGT:PSL:PSO\t0|1:.,phase:.,3\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    assert result["breakend_adjacencies"]
    assert result["breakend_partner_links"] == []
    assert result["unresolved_breakend_partner_link_count"] == 1
    assert result["unresolved_breakend_partner_links"][0]["reason_code"] == (
        "VCF_BREAKEND_PARID_NOT_RECIPROCAL"
    )
