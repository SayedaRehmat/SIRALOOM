from pathlib import Path
import hashlib
import shutil
from uuid import uuid4

import pytest

from backend.app.domain.family_genotype_matrix import build_family_genotype_matrix
from backend.app.domain.vcf import VCFValidationError, parse_vcf
from backend.app.domain.vcf_tools import (
    _validate_source_child_reconciliation,
    normalize_vcf_with_bcftools,
    route_vcf_records,
)
from backend.app.config import settings


def _write_member_vcf(path, sample_name, records):
    header = (
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n'
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
        "normalized_partition_input_artifact_ids": [f"normalized-{analysis_id}"],
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
    assert matrix["provenance_completeness_status"] == "COMPLETE"
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


@pytest.mark.parametrize(
    ("family_id", "first_gt", "second_gt", "first_phase", "second_phase"),
    [
        ("TRANS-KA", "1|0", "0|1", "PHASED", "PHASED"),
        ("CIS-KA", "1|0", "1|0", "PHASED", "PHASED"),
        ("UNRESOLVED-KA", "0/1", "0/1", "UNPHASED", "UNPHASED"),
    ],
)
def test_independent_phase_known_answers_preserve_cis_trans_and_unresolved_without_inference(
    tmp_path, family_id, first_gt, second_gt, first_phase, second_phase,
):
    path = tmp_path / f"{family_id}.vcf"
    _write_member_vcf(path, family_id, [
        f"1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t{first_gt}:35:90:18,17:100",
        f"1\t200\t.\tC\tT\t.\tPASS\t.\tGT:DP:GQ:AD:PS\t{second_gt}:32:88:16,16:100",
    ])
    parsed = _parsed_calls(path, family_id)
    variant_ids = {key: uuid4() for key in parsed}
    sample = _family_sample(
        uuid4(), "PROBAND", uuid4(), uuid4(), uuid4(), family_id,
        {variant_ids[key]: value for key, value in parsed.items()},
    )
    matrix = build_family_genotype_matrix(
        case_id=uuid4(), variant_ids=list(variant_ids.values()),
        samples=[sample], relationships=[],
    )
    calls = matrix["samples"][0]["calls"]
    assert [row["normalized_genotype"] for row in calls] == [first_gt, second_gt]
    assert [row["phase"] for row in calls] == [first_phase, second_phase]
    assert all(row["phase_set"] == "100" for row in calls)
    assert matrix["interpretation_status"] == "NOT_PERFORMED"


def test_independent_relationship_discordance_known_answer_remains_unverified(tmp_path):
    path = tmp_path / "relationship-discordance.vcf"
    _write_member_vcf(path, "FAMILY-REL", [
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:30:90",
    ])
    parsed = _parsed_calls(path, "FAMILY-REL")
    variant_id = uuid4()
    sample = _family_sample(
        uuid4(), "REPORTED_FATHER", uuid4(), uuid4(), uuid4(), "FAMILY-REL",
        {variant_id: next(iter(parsed.values()))},
    )
    relationship = {
        "parent_member_identifier": "REPORTED_FATHER",
        "child_member_identifier": "PROBAND",
        "relationship_type": "PARENT_CHILD",
        "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        "metadata": {
            "reported_relationship": "FATHER",
            "independent_relationship_test": "DISCORDANT",
            "review_status": "REQUIRES_REVIEW",
        },
    }
    matrix = build_family_genotype_matrix(
        case_id=uuid4(), variant_ids=[variant_id], samples=[sample],
        relationships=[relationship],
    )
    assert matrix["relationships_as_recorded"][0]["metadata"]["independent_relationship_test"] == "DISCORDANT"
    assert matrix["relationships_as_recorded"][0]["relationship_status"] == "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED"
    assert matrix["biological_relatedness_status"] == "NOT_ESTABLISHED"
    assert matrix["interpretation_status"] == "NOT_PERFORMED"


def test_independent_locus_ploidy_known_answer_does_not_promote_specimen_region_copy_number(tmp_path):
    path = tmp_path / "locus-ploidy.vcf"
    _write_member_vcf(path, "PLOIDY-SAMPLE", [
        "X\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0:40:99",
    ])
    parsed = _parsed_calls(path, "PLOIDY-SAMPLE")
    variant_id = uuid4()
    sample = _family_sample(
        uuid4(), "PROBAND", uuid4(), uuid4(), uuid4(), "PLOIDY-SAMPLE",
        {variant_id: next(iter(parsed.values()))},
    )
    sample["ploidy_evidence"] = {
        "version": 7,
        "status": "VERIFIED",
        "reference_build": "GRCh38",
        "revision_fingerprint": "a" * 64,
        "region_copy_number": {"chrX:1-155270560": 1},
        "source_type": "LAB_VALIDATED",
        "evidence_reference": "PLOIDY-KA-007",
    }
    matrix = build_family_genotype_matrix(
        case_id=uuid4(), variant_ids=[variant_id], samples=[sample], relationships=[],
    )
    projected = matrix["samples"][0]
    assert projected["ploidy_evidence_status"] == "VERIFIED_RECORDED_LOCUS_POLICY_REQUIRED"
    assert projected["ploidy_interpretation_status"] == "REQUIRES_LOCUS_SPECIFIC_LAB_POLICY"
    assert projected["calls"][0]["call_state"] == "CALL_PRESENT"
    assert matrix["interpretation_status"] == "NOT_PERFORMED"


def test_independent_low_quality_parent_known_answer_preserves_metrics_without_callability_claim(tmp_path):
    path = tmp_path / "low-quality-parent.vcf"
    _write_member_vcf(path, "LOW-GQ-PARENT", [
        "1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD\t0/1:3:2:2,1",
    ])
    parsed = _parsed_calls(path, "LOW-GQ-PARENT")
    variant_id = uuid4()
    parent = _family_sample(
        uuid4(), "FATHER", uuid4(), uuid4(), uuid4(), "LOW-GQ-PARENT",
        {variant_id: next(iter(parsed.values()))},
    )
    matrix = build_family_genotype_matrix(
        case_id=uuid4(), variant_ids=[variant_id], samples=[parent], relationships=[],
    )
    call = matrix["samples"][0]["calls"][0]
    assert call["call_state"] == "CALL_PRESENT"
    assert call["quality_metrics"] == {"DP": "3", "GQ": "2", "AD": "2,1"}
    assert call["quality_assessment_status"] == "NOT_ASSESSED_REQUIRES_LAB_QC_POLICY"
    assert call["callability"] == "NOT_ASSESSED"
    assert matrix["interpretation_status"] == "NOT_PERFORMED"



@pytest.mark.integration
def test_family_matrix_consumes_real_bcftools_normalized_output_with_verified_source_lineage(tmp_path):
    executable = settings.bcftools_executable
    if not (Path(executable).is_file() or shutil.which(executable)):
        pytest.skip("Pinned bcftools executable is unavailable in this test environment")

    reference = Path(__file__).resolve().parents[1] / "fixtures" / "20k" / "GRCh38_test.fa"
    reference_index = Path(str(reference) + ".fai")
    if not reference.is_file() or not reference_index.is_file():
        pytest.skip("Pinned GRCh38 test reference and FAI fixture are unavailable")

    source = tmp_path / "family-source.vcf"
    original_record = "chr1\t10000\t.\tA\tG\t.\tPASS\t.\tGT\t0/1"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=chr1,length=1000000>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tFAMILY-P\n"
        + original_record + "\n",
        encoding="utf-8",
    )

    routed_dir = tmp_path / "routed"
    route_vcf_records(source, routed_dir)
    sequence_input = routed_dir / "sequence-input.vcf"
    normalized = tmp_path / "family-normalized.vcf.gz"
    normalize_vcf_with_bcftools(
        sequence_input,
        normalized,
        reference_fasta=reference,
        expected_bcftools_version=settings.bcftools_version,
        preserve_existing_source_mapping=True,
        bcftools_executable=executable,
    )

    reconciliation = _validate_source_child_reconciliation(sequence_input, normalized)
    assert reconciliation["status"] == "VALIDATED"
    parsed = list(parse_vcf(str(normalized), sample_name="FAMILY-P"))
    assert len(parsed) == 1
    call = parsed[0].sample_calls["FAMILY-P"]
    expected_source_digest = hashlib.sha256(original_record.encode("utf-8")).hexdigest()
    assert call["source_record_sha256"] == expected_source_digest

    variant_id = uuid4()
    sample = _family_sample(
        uuid4(), "PROBAND", uuid4(), uuid4(), uuid4(), "FAMILY-P",
        {variant_id: call},
    )
    matrix = build_family_genotype_matrix(
        case_id=uuid4(), variant_ids=[variant_id], samples=[sample], relationships=[],
    )
    projected = matrix["samples"][0]["calls"][0]
    assert projected["call_state"] == "CALL_PRESENT"
    assert projected["source_record_sha256_status"] == "PRESENT_VALID_SHA256"
    assert projected["source_record_sha256"] == expected_source_digest
