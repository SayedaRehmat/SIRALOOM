from uuid import uuid4

import pytest

from backend.app.domain.family_genotype_matrix import build_family_genotype_matrix
from backend.app.domain.vcf import VCFValidationError, parse_vcf
from backend.app.domain.vcf_tools import route_vcf_records


def _write_member_vcf(path, sample_name, records):
    header = (
        "##fileformat=VCFv4.3\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n"
        "##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n"
        "##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n"
        "##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n"
        "##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n"
        f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{sample_name}\n"
    )
    path.write_text(header + "".join(record + "\n" for record in records), encoding="utf-8")


def _parsed_calls(path, sample_name):
    # Exercise the production intake router: it stamps each eligible source
    # record with an immutable source-record SHA-256 lineage payload before
    # normalization. The matrix must receive that lineage from normalized calls.
    routed_dir = path.parent / f"{path.stem}-{sample_name}-routed"
    routing = route_vcf_records(path, routed_dir)
    assert routing["sequence_records"] > 0
    routed_vcf = routed_dir / "sequence-input.vcf"
    calls = {}
    for record in parse_vcf(str(routed_vcf), sample_name=sample_name):
        call = record.sample_calls[sample_name]
        calls[(record.chrom, record.pos, record.ref, record.alt)] = call
    return calls


def _family_sample(member_id, identifier, specimen_id, analysis_id, artifact_id, sample_name, calls):
    return {
        "member_id": member_id,
        "member_identifier": identifier,
        "relationship_to_proband": "PROBAND" if identifier == "PROBAND" else identifier,
        "sex": "UNKNOWN",
        "affected_status": "AFFECTED" if identifier == "PROBAND" else "UNKNOWN",
        "specimen_id": specimen_id,
        "analysis_id": analysis_id,
        "analysis_version": 1,
        "analysis_reference_build": "GRCh38",
        "artifact_id": artifact_id,
        "artifact_sha256": "a" * 64,
        "sample_name": sample_name,
        "binding_id": uuid4(),
        "binding_fingerprint": "b" * 64,
        "normalization_step_status": "SUCCEEDED",
        "normalization_step_provenance": {
            "step_id": "normalize", "attempt": 1,
            "input_artifacts": [str(artifact_id)],
            "output_artifacts": [f"normalized-{analysis_id}"],
            "metadata": {"normalization_version": "6.0"},
            "started_at": "2026-11-07T00:00:00+00:00",
            "completed_at": "2026-11-07T00:01:00+00:00",
        },
        "normalized_partition_count": 1,
        "ploidy_evidence": None,
        "identity_evidence": [
            {"evidence_type": "CHAIN_OF_CUSTODY", "review_status": "ACCEPTED", "result": "PASS"},
            {"evidence_type": "SAMPLE_IDENTITY_QC", "review_status": "ACCEPTED", "result": "PASS"},
        ],
        "calls": calls,
    }


def test_known_answer_three_member_family_preserves_genotypes_quality_phase_and_missingness(tmp_path):
    proband_path = tmp_path / "proband.vcf"
    father_path = tmp_path / "father.vcf"
    mother_path = tmp_path / "mother.vcf"
    _write_member_vcf(proband_path, "FAM-P", [
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t0/1:42:99:20,22:.",
        "1\t200\t.\tC\tT\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t1|0:30:80:12,18:200",
        "1\t300\t.\tG\tA\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t./.:0:0:0,0:.",
        "1\t400\t.\tC\tG,T\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t0/2:8:5:4,0,4:.",
    ])
    _write_member_vcf(father_path, "FAM-F", [
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t0/1:25:70:12,13:.",
        "1\t200\t.\tC\tT\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t./.:0:0:0,0:.",
    ])
    _write_member_vcf(mother_path, "FAM-M", [
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t0/0:38:99:38,0:.",
        "1\t300\t.\tG\tA\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t0/1:3:5:2,1:.",
    ])

    parsed = {
        "PROBAND": _parsed_calls(proband_path, "FAM-P"),
        "FATHER": _parsed_calls(father_path, "FAM-F"),
        "MOTHER": _parsed_calls(mother_path, "FAM-M"),
    }
    variant_keys = [
        ("1", 100, "A", "G"),
        ("1", 200, "C", "T"),
        ("1", 300, "G", "A"),
        ("1", 400, "C", "G"),
        ("1", 400, "C", "T"),
    ]
    variant_ids = {key: uuid4() for key in variant_keys}
    samples = []
    for identifier, sample_name in (("PROBAND", "FAM-P"), ("FATHER", "FAM-F"), ("MOTHER", "FAM-M")):
        calls = {
            variant_ids[key]: call
            for key, call in parsed[identifier].items()
        }
        samples.append(_family_sample(
            uuid4(), identifier, uuid4(), uuid4(), uuid4(), sample_name, calls,
        ))

    matrix = build_family_genotype_matrix(
        case_id=uuid4(),
        variant_ids=list(variant_ids.values()),
        samples=samples,
        relationships=[{
            "parent_member_identifier": "FATHER",
            "child_member_identifier": "PROBAND",
            "relationship_type": "PARENT_CHILD",
            "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        }, {
            "parent_member_identifier": "MOTHER",
            "child_member_identifier": "PROBAND",
            "relationship_type": "PARENT_CHILD",
            "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        }],
    )
    by_member = {sample["member_identifier"]: sample for sample in matrix["samples"]}

    def call(member, key):
        return next(row for row in by_member[member]["calls"] if row["variant_id"] == str(variant_ids[key]))

    assert call("PROBAND", ("1", 100, "A", "G"))["call_state"] == "CALL_PRESENT"
    for sample in matrix["samples"]:
        for row in sample["calls"]:
            if row["call_state"] != "NO_RECORD":
                assert row["source_record_sha256_status"] == "PRESENT_VALID_SHA256"
                assert len(row["source_record_sha256"]) == 64
    assert call("FATHER", ("1", 100, "A", "G"))["normalized_genotype"] == "0/1"
    assert call("MOTHER", ("1", 100, "A", "G"))["normalized_genotype"] == "0/0"
    phased = call("PROBAND", ("1", 200, "C", "T"))
    assert phased["normalized_genotype"] == "1|0"
    assert phased["phase"] == "PHASED"
    assert phased["phase_set"] == "200"
    assert call("FATHER", ("1", 200, "C", "T"))["call_state"] == "NO_CALL"
    assert call("MOTHER", ("1", 200, "C", "T"))["call_state"] == "NO_RECORD"
    low_quality = call("MOTHER", ("1", 300, "G", "A"))
    assert low_quality["quality_metrics"] == {"DP": "3", "GQ": "5", "AD": "2,1"}
    assert low_quality["call_state"] == "CALL_PRESENT"
    other_alt = call("PROBAND", ("1", 400, "C", "G"))
    assert other_alt["call_state"] == "OTHER_ALT_PRESENT"
    selected_alt = call("PROBAND", ("1", 400, "C", "T"))
    assert selected_alt["call_state"] == "CALL_PRESENT"
    assert selected_alt["selected_alt_dosage"] == 1
    assert low_quality["quality_assessment_status"] == "NOT_ASSESSED_REQUIRES_LAB_QC_POLICY"
    assert matrix["interpretation_status"] == "NOT_PERFORMED"
    assert matrix["callability_status"] == "NOT_ASSESSED; REQUIRES_LAB_QC_POLICY"
    assert matrix["ploidy_status"] == "PROVENANCE_ONLY; LOCUS_SPECIFIC_POLICY_NOT_APPLIED"
    assert matrix["qualification_status"] == "PROVENANCE_PROJECTION_ONLY_NOT_CLINICALLY_QUALIFIED"
    assert all(
        sample["identity_interpretation"].endswith("BIOLOGICAL_RELATEDNESS_NOT_ESTABLISHED")
        for sample in matrix["samples"]
    )
    assert all(
        relationship["relationship_status"] == "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED"
        for relationship in matrix["relationships_as_recorded"]
    )


def test_family_sample_selection_rejects_sample_swap_and_unselected_multisample_vcf(tmp_path):
    path = tmp_path / "family.vcf"
    header = (
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tFAM-P\tFAM-F\n"
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\t0/0\n"
    )
    path.write_text(header, encoding="utf-8")

    with pytest.raises(VCFValidationError, match="explicit sample_name"):
        list(parse_vcf(str(path)))
    with pytest.raises(VCFValidationError, match="not present"):
        list(parse_vcf(str(path), sample_name="FAM-M"))

    selected = list(parse_vcf(str(path), sample_name="FAM-F"))
    assert len(selected) == 1
    assert set(selected[0].sample_calls) == {"FAM-F"}
    assert selected[0].sample_calls["FAM-F"]["normalized_genotype"] == "0/0"
