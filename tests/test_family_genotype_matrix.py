from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi import HTTPException

from backend.app.domain.family_genotype_matrix import build_family_genotype_matrix
from backend.app.api.v1 import pedigree
from backend.app.infrastructure.db.models import (
    Analysis, Artifact, Case, PedigreeMember, PedigreeSampleBinding,
    Specimen, Variant,
)


def _sample(member_id, identifier, calls):
    return {
        "member_id": member_id,
        "member_identifier": identifier,
        "relationship_to_proband": "PROBAND" if identifier == "PROBAND" else "FATHER",
        "sex": "UNKNOWN",
        "affected_status": "AFFECTED" if identifier == "PROBAND" else "UNAFFECTED",
        "specimen_id": uuid4(),
        "analysis_id": uuid4(),
        "analysis_version": 1,
        "artifact_id": uuid4(),
        "artifact_sha256": "a" * 64,
        "sample_name": identifier,
        "binding_id": uuid4(),
        "binding_fingerprint": "b" * 64,
        "normalization_step_status": "SUCCEEDED",
        "normalized_partition_count": 2,
        "ploidy_evidence": None,
        "identity_evidence": [],
        "calls": calls,
    }


def test_family_matrix_does_not_infer_reference_for_absent_variant_or_no_call():
    case_id, father_id, proband_id = uuid4(), uuid4(), uuid4()
    observed_variant, absent_variant, partial_variant = uuid4(), uuid4(), uuid4()
    father = _sample(father_id, "FATHER", {
        observed_variant: {
            "sample_name": "FATHER",
            "genotype": "./.",
            "normalized_genotype": "./.",
            "missing_allele_count": 2,
            "format_values": {"DP": "18", "GQ": "0"},
        },
        partial_variant: {
            "sample_name": "FATHER",
            "genotype": "0/1",
            "normalized_genotype": "0/1",
            "missing_allele_count": 1,
        },
    })
    proband = _sample(proband_id, "PROBAND", {
        observed_variant: {
            "sample_name": "PROBAND",
            "source_genotype": "0|1",
            "normalized_genotype": "0|1",
            "normalized_zygosity": "HET",
            "selected_alt_dosage": 1,
            "reference_allele_dosage": 1,
            "phase": "PHASED",
            "phase_set": "1200",
            "format_values": {"DP": "42", "GQ": "99", "AD": [20, 22]},
            "source_record_sha256": "c" * 64,
            "source_record_index": 7,
        },
    })

    matrix = build_family_genotype_matrix(
        case_id=case_id,
        variant_ids=[observed_variant, absent_variant, partial_variant],
        samples=[proband, father],
        relationships=[{
            "parent_member_identifier": "FATHER",
            "child_member_identifier": "PROBAND",
            "relationship_type": "PARENT_CHILD",
            "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        }],
    )

    by_member = {sample["member_identifier"]: sample for sample in matrix["samples"]}
    father_calls = {row["variant_id"]: row for row in by_member["FATHER"]["calls"]}
    proband_calls = {row["variant_id"]: row for row in by_member["PROBAND"]["calls"]}

    assert father_calls[str(observed_variant)]["call_state"] == "NO_CALL"
    assert father_calls[str(observed_variant)]["callability"] == "NOT_ASSESSED"
    assert father_calls[str(absent_variant)]["call_state"] == "NO_RECORD"
    assert father_calls[str(absent_variant)]["reference_allele_dosage"] is None
    assert father_calls[str(partial_variant)]["call_state"] == "PARTIAL_NO_CALL"
    assert proband_calls[str(observed_variant)]["call_state"] == "CALL_PRESENT"
    assert proband_calls[str(observed_variant)]["phase"] == "PHASED"
    assert proband_calls[str(observed_variant)]["phase_set"] == "1200"
    assert proband_calls[str(observed_variant)]["quality_metrics"] == {
        "DP": "42", "GQ": "99", "AD": [20, 22],
    }
    assert proband_calls[str(observed_variant)]["source_record_sha256"] == "c" * 64
    assert matrix["interpretation_status"] == "NOT_PERFORMED"
    assert matrix["biological_relatedness_status"] == "NOT_ESTABLISHED"


def test_family_matrix_fingerprint_is_independent_of_sample_input_order():
    case_id, member_a, member_b, variant_id = (uuid4() for _ in range(4))
    a = _sample(member_a, "A", {variant_id: {"sample_name": "A", "genotype": "0/1"}})
    b = _sample(member_b, "B", {variant_id: {"sample_name": "B", "genotype": "0/0"}})
    relationships = [{
        "parent_member_identifier": "A",
        "child_member_identifier": "B",
        "relationship_type": "PARENT_CHILD",
    }]
    first = build_family_genotype_matrix(
        case_id=case_id, variant_ids=[variant_id], samples=[a, b], relationships=relationships,
    )
    second = build_family_genotype_matrix(
        case_id=case_id, variant_ids=[variant_id], samples=[b, a], relationships=relationships,
    )
    assert first["matrix_fingerprint"] == second["matrix_fingerprint"]


def test_family_matrix_preserves_multiple_specimens_and_assays_for_one_member():
    case_id, member_id, variant_id = uuid4(), uuid4(), uuid4()
    first = _sample(member_id, "MEMBER", {variant_id: {"sample_name": "ASSAY-A", "genotype": "0/1"}})
    second = _sample(member_id, "MEMBER", {variant_id: {"sample_name": "ASSAY-B", "genotype": "0/0"}})
    first["sample_name"] = "ASSAY-A"
    second["sample_name"] = "ASSAY-B"
    first["specimen_id"] = uuid4()
    second["specimen_id"] = uuid4()
    first["analysis_id"] = uuid4()
    second["analysis_id"] = uuid4()
    matrix = build_family_genotype_matrix(
        case_id=case_id, variant_ids=[variant_id], samples=[second, first], relationships=[],
    )
    assert len(matrix["samples"]) == 2
    assert {sample["vcf_sample_name"] for sample in matrix["samples"]} == {"ASSAY-A", "ASSAY-B"}
    assert all(sample["member_id"] == str(member_id) for sample in matrix["samples"])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _MatrixDB:
    def __init__(self, objects, scalar_rows, query_rows):
        self.objects = objects
        self.scalar_rows = list(scalar_rows)
        self.query_rows = list(query_rows)

    def get(self, model, identifier, **_kwargs):
        return self.objects.get((model, identifier))

    def refresh(self, *_args, **_kwargs):
        return None

    def scalar(self, _statement):
        return self.scalar_rows.pop(0)

    def scalars(self, _statement):
        return _Rows(self.query_rows.pop(0))


def test_matrix_endpoint_joins_verified_sample_calls_to_source_artifact_provenance(monkeypatch):
    case_id, member_id, specimen_id, analysis_id, artifact_id, binding_id, variant_id = (
        uuid4() for _ in range(7)
    )
    user_id = uuid4()
    case = SimpleNamespace(id=case_id)
    member = SimpleNamespace(
        id=member_id, case_id=case_id, member_identifier="PROBAND",
        relationship_to_proband="PROBAND", sex="UNKNOWN", affected_status="AFFECTED",
    )
    specimen = SimpleNamespace(id=specimen_id, case_id=case_id)
    artifact = SimpleNamespace(
        id=artifact_id, case_id=case_id, sha256="a" * 64, specimen_id=specimen_id,
    )
    analysis = SimpleNamespace(
        id=analysis_id, case_id=case_id, analysis_version=3, reference_build="GRCh38",
        configuration={"input_artifact_id": str(artifact_id), "vcf_sample_name": "FAM-01"},
    )
    binding = SimpleNamespace(
        id=binding_id, case_id=case_id, pedigree_member_id=member_id,
        specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
        source_artifact_sha256="a" * 64, sample_name="FAM-01",
        binding_status="VERIFIED", binding_fingerprint="b" * 64,
    )
    variant = SimpleNamespace(id=variant_id, genome_build="GRCh38")
    workflow = SimpleNamespace(status="SUCCEEDED", input_artifacts=[str(artifact_id)])
    partition = SimpleNamespace(ordinal=0)
    db = _MatrixDB(
        {
            (Case, case_id): case,
            (PedigreeSampleBinding, binding_id): binding,
            (PedigreeMember, member_id): member,
            (Specimen, specimen_id): specimen,
            (Analysis, analysis_id): analysis,
            (Artifact, artifact_id): artifact,
            (Variant, variant_id): variant,
        },
        scalar_rows=[None, workflow],
        query_rows=[
            [partition],
            [
                SimpleNamespace(
                    id=uuid4(), evidence_type="CHAIN_OF_CUSTODY", result="PASS",
                    method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
                    evidence_reference="LIMS-ACCESSION-1", evidence_fingerprint="e" * 64,
                    review_status="ACCEPTED", reviewed_by=user_id, reviewed_at=None,
                    supersedes_evidence_id=None,
                ),
                SimpleNamespace(
                    id=uuid4(), evidence_type="SAMPLE_IDENTITY_QC", result="PASS",
                    method="SNP_FINGERPRINT_CONCORDANCE", method_version="2",
                    evidence_reference="IDENTITY-QC-REPORT-1", evidence_fingerprint="f" * 64,
                    review_status="ACCEPTED", reviewed_by=user_id, reviewed_at=None,
                    supersedes_evidence_id=None,
                ),
            ],
            [], [member], [],
        ],
    )
    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(
        pedigree, "get_analysis_sample_calls",
        lambda *_args: {
            variant_id: {
                "sample_name": "FAM-01", "genotype": "0/1",
                "normalized_genotype": "0/1", "selected_alt_dosage": 1,
                "source_record_sha256": "c" * 64,
            }
        },
    )

    result = pedigree.get_family_genotype_matrix(
        case_id,
        pedigree.GenotypeMatrixInput(binding_ids=[binding_id], variant_ids=[variant_id]),
        db,
        SimpleNamespace(user_id=user_id),
    )

    assert result["samples"][0]["source_artifact_sha256"] == "a" * 64
    assert result["samples"][0]["vcf_sample_name"] == "FAM-01"
    assert {item["evidence_type"] for item in result["samples"][0]["identity_evidence"]} == {
        "CHAIN_OF_CUSTODY", "SAMPLE_IDENTITY_QC",
    }
    assert result["samples"][0]["calls"][0]["call_state"] == "CALL_PRESENT"
    assert result["samples"][0]["calls"][0]["source_record_sha256"] == "c" * 64
    assert result["interpretation_status"] == "NOT_PERFORMED"


def test_matrix_endpoint_rejects_superseded_binding(monkeypatch):
    case_id, binding_id, variant_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id)
    binding = SimpleNamespace(id=binding_id, case_id=case_id, binding_status="VERIFIED")
    variant = SimpleNamespace(id=variant_id, genome_build="GRCh38")
    successor = SimpleNamespace(id=uuid4())
    db = _MatrixDB(
        {
            (Case, case_id): case,
            (PedigreeSampleBinding, binding_id): binding,
            (Variant, variant_id): variant,
        },
        scalar_rows=[successor],
        query_rows=[],
    )
    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)

    with pytest.raises(HTTPException) as exc:
        pedigree.get_family_genotype_matrix(
            case_id,
            pedigree.GenotypeMatrixInput(binding_ids=[binding_id], variant_ids=[variant_id]),
            db,
            SimpleNamespace(user_id=uuid4()),
        )
    assert getattr(exc.value, "status_code", None) == 409


def test_matrix_endpoint_composes_two_assays_for_same_family_member(monkeypatch):
    case_id, member_id, variant_id, user_id = (uuid4() for _ in range(4))
    case = SimpleNamespace(id=case_id)
    member = SimpleNamespace(
        id=member_id, case_id=case_id, member_identifier="PROBAND",
        relationship_to_proband="PROBAND", sex="UNKNOWN", affected_status="AFFECTED",
    )
    specimens = [SimpleNamespace(id=uuid4(), case_id=case_id) for _ in range(2)]
    artifacts = [
        SimpleNamespace(id=uuid4(), case_id=case_id, sha256=digest, specimen_id=specimen.id)
        for specimen, digest in zip(specimens, ("a" * 64, "b" * 64))
    ]
    analyses = [
        SimpleNamespace(
            id=uuid4(), case_id=case_id, analysis_version=index + 1,
            reference_build="GRCh38",
            configuration={
                "input_artifact_id": str(artifacts[index].id),
                "vcf_sample_name": f"PROBAND_ASSAY_{index + 1}",
            },
        )
        for index in range(2)
    ]
    bindings = [
        SimpleNamespace(
            id=uuid4(), case_id=case_id, pedigree_member_id=member_id,
            specimen_id=specimens[index].id, analysis_id=analyses[index].id,
            artifact_id=artifacts[index].id, source_artifact_sha256=artifacts[index].sha256,
            sample_name=f"PROBAND_ASSAY_{index + 1}", binding_status="VERIFIED",
            binding_fingerprint=("c" if index == 0 else "d") * 64,
        )
        for index in range(2)
    ]
    variant = SimpleNamespace(id=variant_id, genome_build="GRCh38")
    workflows = [
        SimpleNamespace(status="SUCCEEDED", input_artifacts=[str(artifacts[index].id)])
        for index in range(2)
    ]
    partitions = [[SimpleNamespace(ordinal=0)], [SimpleNamespace(ordinal=0)]]
    identity_evidence = [
        [
            SimpleNamespace(
                id=uuid4(), evidence_type=kind, result="PASS", method="LAB_QC",
                method_version="1", evidence_reference=f"{kind}-1",
                evidence_fingerprint=("e" if kind == "CHAIN_OF_CUSTODY" else "f") * 64,
                review_status="ACCEPTED", reviewed_by=user_id, reviewed_at=None,
                supersedes_evidence_id=None,
            )
            for kind in ("CHAIN_OF_CUSTODY", "SAMPLE_IDENTITY_QC")
        ]
        for _ in range(2)
    ]

    class MultiAssayDB:
        def get(self, model, identifier, **_kwargs):
            objects = {
                (Case, case_id): case,
                (Variant, variant_id): variant,
            }
            for index in range(2):
                objects.update({
                    (PedigreeSampleBinding, bindings[index].id): bindings[index],
                    (PedigreeMember, member_id): member,
                    (Specimen, specimens[index].id): specimens[index],
                    (Analysis, analyses[index].id): analyses[index],
                    (Artifact, artifacts[index].id): artifacts[index],
                })
            return objects.get((model, identifier))

        def refresh(self, *_args, **_kwargs):
            return None

        def scalar(self, statement):
            sql = str(statement)
            if "pedigree_sample_bindings" in sql:
                return None
            if "workflow_steps" in sql:
                analysis_id = next(
                    analysis.id for analysis in analyses if str(analysis.id) in sql
                ) if any(str(analysis.id) in sql for analysis in analyses) else None
                # SQLAlchemy binds are not rendered into the string; preserve call order.
                return workflows.pop(0)
            raise AssertionError(f"Unexpected scalar query: {sql}")

        def scalars(self, statement):
            sql = str(statement)
            if "analysis_partitions" in sql:
                return _Rows(partitions.pop(0))
            if "pedigree_sample_identity_evidence" in sql:
                return _Rows(identity_evidence.pop(0))
            if "specimen_ploidy_evidence_revisions" in sql:
                return _Rows([])
            if "pedigree_members" in sql:
                return _Rows([member])
            if "pedigree_relationships" in sql:
                return _Rows([])
            raise AssertionError(f"Unexpected collection query: {sql}")

    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    calls_by_analysis = {
        analyses[0].id: {
            variant_id: {
                "sample_name": "PROBAND_ASSAY_1", "genotype": "0/1",
                "normalized_genotype": "0/1", "source_record_sha256": "1" * 64,
            },
        },
        analyses[1].id: {
            variant_id: {
                "sample_name": "PROBAND_ASSAY_2", "genotype": "0/0",
                "normalized_genotype": "0/0", "source_record_sha256": "2" * 64,
            },
        },
    }
    monkeypatch.setattr(
        pedigree, "get_analysis_sample_calls",
        lambda _db, analysis_id: calls_by_analysis[analysis_id],
    )

    result = pedigree.get_family_genotype_matrix(
        case_id,
        pedigree.GenotypeMatrixInput(
            binding_ids=[bindings[0].id, bindings[1].id],
            variant_ids=[variant_id],
        ),
        MultiAssayDB(),
        SimpleNamespace(user_id=user_id),
    )

    assert len(result["samples"]) == 2
    assert {sample["member_id"] for sample in result["samples"]} == {str(member_id)}
    assert {sample["vcf_sample_name"] for sample in result["samples"]} == {
        "PROBAND_ASSAY_1", "PROBAND_ASSAY_2",
    }
    observed = {
        sample["vcf_sample_name"]: sample["calls"][0]["normalized_genotype"]
        for sample in result["samples"]
    }
    assert observed == {"PROBAND_ASSAY_1": "0/1", "PROBAND_ASSAY_2": "0/0"}
