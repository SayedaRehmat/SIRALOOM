from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import pedigree
from backend.app.api.v1.pedigree import AssessmentInput
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Evidence,
    FamilyGenotypeMatrixSnapshot,
    InheritanceAssessment,
    Organization,
    PedigreeMember,
    SegregationObservation,
    SegregationObservationRevision,
    User,
    Variant,
)
from backend.app.inheritance import (
    FamilyObservation,
    assess_model,
    assessment_projection,
    evidence_projection,
    fingerprint,
    normalize_model,
)


def test_pedigree_report_mutations_lock_the_analysis_row(monkeypatch):
    analysis_id, case_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    case = SimpleNamespace(id=case_id)
    permission_checks = []

    class FakeDb:
        def scalar(self, statement):
            assert statement._for_update_arg is not None
            return analysis

        def get(self, model, object_id):
            assert model is Case
            assert object_id == case_id
            return case

    monkeypatch.setattr(
        pedigree,
        "require_case_permission",
        lambda _case, _principal, _db, permission: permission_checks.append(permission),
    )
    principal = SimpleNamespace(user_id=uuid4())

    assert pedigree._lock_analysis_for_pedigree(
        FakeDb(), analysis_id, principal, "write"
    ) is analysis
    assert permission_checks == ["write"]


def test_pedigree_snapshot_records_stable_member_and_relationship_context():
    case_id, father_id, proband_id = uuid4(), uuid4(), uuid4()
    father = SimpleNamespace(
        id=father_id, member_identifier="father", relationship_to_proband="FATHER",
        sex="MALE", affected_status="UNAFFECTED", is_proband=False, sampled=True,
        specimen_id=None, metadata_json={},
    )
    proband = SimpleNamespace(
        id=proband_id, member_identifier="proband", relationship_to_proband="PROBAND",
        sex="UNKNOWN", affected_status="AFFECTED", is_proband=True, sampled=True,
        specimen_id=None, metadata_json={},
    )
    relationship = SimpleNamespace(
        id=uuid4(), case_id=case_id,
        parent_member_id=father_id, child_member_id=proband_id,
        relationship_type="PARENT_CHILD", metadata_json={},
    )

    class FakeDb:
        def __init__(self):
            self.rows = [[proband, father], [relationship], [], []]

        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return self.rows.pop(0)

    snapshot = pedigree._pedigree_context_snapshot(FakeDb(), case_id)

    assert snapshot["schema_version"] == 2
    assert [member["member_identifier"] for member in snapshot["members"]] == [
        "father", "proband"
    ]
    assert snapshot["relationships"] == [{
        "parent_member_identifier": "father",
        "child_member_identifier": "proband",
        "relationship_type": "PARENT_CHILD",
        "metadata": {},
        "relationship_revision_version": 1,
        "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
    }]


def test_pedigree_member_and_relationship_changes_create_reanalysis_candidates(monkeypatch):
    case_id, parent_id, child_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, case_identifier="PED-CHANGE-001")
    parent = SimpleNamespace(
        id=parent_id, case_id=case_id, member_identifier="parent",
    )
    child = SimpleNamespace(
        id=child_id, case_id=case_id, member_identifier="proband",
    )
    principal = SimpleNamespace(user_id=uuid4())

    class FakeResult:
        def all(self):
            return []

    class FakeDb:
        def __init__(self):
            self.added = []
            self.commits = 0

        def get(self, model, object_id, **_kwargs):
            if model is Case and object_id == case_id:
                return case
            if model is PedigreeMember and object_id == parent_id:
                return parent
            if model is PedigreeMember and object_id == child_id:
                return child
            raise AssertionError(f"Unexpected lookup: {model!r} {object_id!r}")

        def refresh(self, *_args, **_kwargs):
            pass

        def scalar(self, _query):
            return None

        def scalars(self, _query):
            return FakeResult()

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.commits += 1

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    candidate_calls = []
    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    monkeypatch.setattr(
        pedigree,
        "create_case_change_candidates",
        lambda _db, **kwargs: candidate_calls.append(kwargs) or [],
    )
    monkeypatch.setattr(
        pedigree,
        "_current_pedigree",
        lambda *_args: (
            [
                {"id": str(parent_id), "is_proband": False},
                {"id": str(child_id), "is_proband": True},
            ],
            [],
            [],
            [],
        ),
    )

    member_db = FakeDb()
    pedigree.add_member(
        case_id,
        pedigree.MemberInput(member_identifier="sibling", affected_status="UNKNOWN"),
        member_db,
        principal,
    )
    relationship_db = FakeDb()
    pedigree.add_relationship(
        case_id,
        pedigree.RelationshipInput(
            parent_member_id=parent_id,
            child_member_id=child_id,
        ),
        relationship_db,
        principal,
    )

    assert [call["trigger_type"] for call in candidate_calls] == [
        "PEDIGREE_UPDATE",
        "PEDIGREE_UPDATE",
    ]
    assert candidate_calls[0]["metadata"]["change_type"] == "MEMBER_ADDED"
    assert candidate_calls[1]["metadata"]["change_type"] == "RELATIONSHIP_ADDED"
    assert member_db.commits == relationship_db.commits == 1


def test_segregation_write_overrides_client_pedigree_snapshot(monkeypatch):
    analysis_id, variant_id, case_id, member_id = (uuid4() for _ in range(4))
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    member = SimpleNamespace(id=member_id, case_id=case_id, member_identifier="proband")
    principal = SimpleNamespace(user_id=uuid4())
    expected_snapshot = {"schema_version": 1, "members": [], "relationships": []}

    class FakeDb:
        def __init__(self):
            self.added = []
            self.committed = False

        def get(self, model, _identifier):
            assert model is pedigree.PedigreeMember
            return member

        def scalar(self, _query):
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    lock_permissions = []
    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        pedigree,
        "_lock_analysis_for_pedigree",
        lambda _db, _analysis_id, _principal, permission: lock_permissions.append(permission) or analysis,
    )
    monkeypatch.setattr(
        pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id)
    )
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "_pedigree_context_snapshot", lambda *_args: expected_snapshot)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    body = pedigree.SegregationInput(
        pedigree_member_id=member_id,
        genotype="0/1",
        metadata={"pedigree_context_snapshot": {"schema_version": 999}},
    )
    db = FakeDb()

    pedigree.add_segregation(analysis_id, variant_id, body, db, principal)

    row = next(item for item in db.added if isinstance(item, SegregationObservation))
    assert row.metadata_json["pedigree_context_snapshot"] == expected_snapshot
    assert row.source == "MANUALLY_REPORTED"
    assert db.committed is True
    assert lock_permissions == ["write"]


def test_m10_model_aliases_and_fingerprint_are_deterministic():
    assert normalize_model("autosomal dominant") == "AD"
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/0", "HOM_REF"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    assert fingerprint(observations) == fingerprint(list(reversed(observations)))


def test_inheritance_observations_do_not_produce_unvalidated_compatibility_claims():
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/0", "HOM_REF"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    result = assess_model("AD", observations)
    assert result["status"] == "REQUIRES_REVIEW"
    assert result["observations_available"] == 2
    assert "score" not in result
    assert "not implemented" in result["rationale"]


def test_unaffected_carrier_is_not_called_a_contradiction_without_penetrance_context():
    observations = [
        FamilyObservation("MOTHER", "FEMALE", "UNAFFECTED", "0/1", "HET"),
        FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET"),
    ]
    result = assess_model("AD", observations)
    assert result["status"] == "REQUIRES_REVIEW"
    assert "score" not in result


def test_single_heterozygous_observation_does_not_claim_recessive_contradiction():
    observations = [FamilyObservation("PROBAND", "FEMALE", "AFFECTED", "0/1", "HET")]
    result = assess_model("AR", observations)
    assert result["status"] == "REQUIRES_REVIEW"


def test_m10_no_genotype_data_is_insufficient():
    observations = [FamilyObservation("PROBAND", "MALE", "AFFECTED", None, None)]
    result = assess_model("AD", observations)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "score" not in result


def test_unknown_phenotype_and_missing_genotype_are_not_counted_as_interpretable():
    result = assess_model(
        "AD",
        [
            FamilyObservation("MEMBER1", "UNKNOWN", "UNKNOWN", "0/1", None),
            FamilyObservation("MEMBER2", "UNKNOWN", "AFFECTED", "./.", None),
        ],
    )

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["observations_available"] == 0


def test_malformed_vcf_genotype_is_not_counted_as_interpretable_even_with_zygosity():
    result = assess_model(
        "AD",
        [FamilyObservation("PROBAND", "FEMALE", "AFFECTED", "heterozygous-ish", "HET")],
    )

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["observations_available"] == 0


def test_valid_vcf_genotype_syntax_and_explicit_zygosity_are_accepted_as_observations():
    result = assess_model(
        "AD",
        [
            FamilyObservation("PARENT", "UNKNOWN", "UNAFFECTED", "0|1", None),
            FamilyObservation("PROBAND", "UNKNOWN", "AFFECTED", None, "HET"),
        ],
    )

    assert result["status"] == "REQUIRES_REVIEW"
    assert result["observations_available"] == 2
    assert "not implemented" in result["rationale"]


def test_de_novo_model_requires_review_without_parental_and_confirmation_inputs():
    result = assess_model(
        "DE_NOVO",
        [FamilyObservation("PROBAND", "MALE", "AFFECTED", "0/1", "HET")],
    )

    assert result["status"] == "REQUIRES_REVIEW"
    assert "parental" in result["rationale"]
    assert "score" not in result


def test_legacy_assessment_projection_retires_persisted_heuristic_claims():
    status, rationale = assessment_projection(
        status="CONSISTENT", rationale="Legacy status", score=80
    )
    assert status == "REQUIRES_REVIEW"
    assert "Retired unvalidated heuristic" in rationale

    statement, payload = evidence_projection(
        source_name="SIRALOOM Inheritance Engine",
        source_version="M10",
        statement="Inheritance model AD: CONSISTENT",
        payload={"status": "CONSISTENT", "score": 80},
    )
    assert "retired" in statement
    assert payload["status"] == "REQUIRES_REVIEW"
    assert "score" not in payload
    assert payload["legacy_result_retired"] is True


def test_assessment_api_persists_neutral_review_state_without_a_score(monkeypatch):
    analysis_id, variant_id, case_id, member_id = uuid4(), uuid4(), uuid4(), uuid4()
    principal = SimpleNamespace(user_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    observation = SimpleNamespace(
        id=uuid4(),
        pedigree_member_id=member_id,
        genotype="0/1",
        zygosity="HET",
        phenotype_status="AFFECTED",
    )
    member = SimpleNamespace(
        id=member_id,
        member_identifier="PROBAND",
        sex="UNKNOWN",
        affected_status="AFFECTED",
    )

    class FakeDb:
        def __init__(self):
            self.rows = [[observation], [member]]
            self.added = []
            self.committed = False

        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return self.rows.pop(0)

        def scalar(self, _query):
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    lock_permissions = []
    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(
        pedigree,
        "_lock_analysis_for_pedigree",
        lambda _db, _analysis_id, _principal, permission: lock_permissions.append(permission) or analysis,
    )
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    db = FakeDb()

    result = pedigree.assess_inheritance(
        analysis_id,
        variant_id,
        AssessmentInput(models=["DE_NOVO"]),
        db,
        principal,
    )

    assert result["results"][0]["status"] == "REQUIRES_REVIEW"
    assert result["results"][0]["observations_available"] == 0
    assert lock_permissions == ["review"]
    assert "score" not in result["results"][0]
    assert "score" not in result
    assert db.committed is True
    assessment = next(row for row in db.added if hasattr(row, "observation_fingerprint"))
    evidence = next(row for row in db.added if getattr(row, "evidence_type", None) == "SEGREGATION")
    assert assessment.score is None
    assert evidence.source_version == "M12_FAMILY_MATRIX_REVIEW_CONTEXT"
    assert "score" not in evidence.payload
    assert evidence.payload["status"] == "REQUIRES_REVIEW"


def test_identical_inheritance_assessment_retry_reuses_rows_and_does_not_duplicate_audit(monkeypatch):
    analysis_id, variant_id, case_id, member_id = (uuid4() for _ in range(4))
    principal = SimpleNamespace(user_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    observation = SimpleNamespace(
        id=uuid4(), pedigree_member_id=member_id, genotype="0/1",
        zygosity="HET", phenotype_status="AFFECTED",
    )
    member = SimpleNamespace(
        id=member_id, member_identifier="PROBAND", sex="UNKNOWN",
        affected_status="AFFECTED",
    )
    # Manual SegregationObservation values are deliberately excluded from
    # source-derived inheritance assessment until a verified family matrix is bound.
    obs = []
    observation_fingerprint = fingerprint(obs)
    assessment = InheritanceAssessment(
        id=uuid4(), analysis_id=analysis_id, variant_id=variant_id, model="AD",
        status="REQUIRES_REVIEW", score=None,
        rationale=assess_model("AD", obs)["rationale"],
        observation_fingerprint=observation_fingerprint, reviewer_note="review context",
        created_by=str(principal.user_id),
    )
    payload = {
        "model": "AD", "status": "REQUIRES_REVIEW", "observations_available": 0,
        "observation_fingerprint": observation_fingerprint,
        "family_matrix_fingerprint": None, "family_matrix_snapshot_id": None,
        "family_matrix_binding_ids": [], "reviewer_note": "review context",
        "interpretation": "REQUIRES_HUMAN_REVIEW",
        "manual_segregation_rows_excluded": True,
        "manual_segregation_observation_ids": [str(observation.id)],
    }
    import hashlib
    import json

    evidence_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = SimpleNamespace(id=uuid4(), evidence_fingerprint=evidence_fingerprint)

    class FakeDb:
        def __init__(self):
            self.rows = [[observation], [member]]
            self.scalar_results = [assessment, evidence]
            self.added = []
            self.committed = False

        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return self.rows.pop(0)

        def scalar(self, _query):
            return self.scalar_results.pop(0)

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    class FakeAudit:
        events = []

        def __init__(self, _db):
            pass

        def record(self, **kwargs):
            self.events.append(kwargs)

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    FakeAudit.events.clear()
    db = FakeDb()

    result = pedigree.assess_inheritance(
        analysis_id, variant_id,
        AssessmentInput(models=["AD"], reviewer_note="review context"), db, principal,
    )

    assert result["results"][0]["id"] == str(assessment.id)
    assert result["results"][0]["reviewer_note"] == "review context"
    assert not any(isinstance(row, InheritanceAssessment) for row in db.added)
    assert not any(isinstance(row, Evidence) for row in db.added)
    assert FakeAudit.events == []
    assert db.committed is True


def test_identical_inheritance_assessment_retry_obeys_database_uniqueness(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    organization = Organization(id=uuid4(), name="Test Lab")
    reviewer = User(
        id=uuid4(), organization_id=organization.id, display_name="Reviewer",
        email="reviewer@example.org", role="lab_director", status="ACTIVE",
    )
    case = Case(
        id=uuid4(), organization_id=organization.id, case_identifier="PED-RETRY",
        status="ACTIVE", clinical_context={}, language="en", created_by=reviewer.id,
    )
    analysis = Analysis(
        id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1", workflow_version="1", status="REQUIRES_REVIEW",
        reference_build="GRCh38", configuration={}, created_by=reviewer.id,
    )
    variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=10,
        reference="A", alternate="G", normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:10:A:G:{uuid4()}", identifiers={},
    )
    member = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="PROBAND", sex="UNKNOWN",
        affected_status="AFFECTED", is_proband=True, sampled=False, metadata_json={},
    )
    observation = SegregationObservation(
        id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
        pedigree_member_id=member.id, genotype="0/1", zygosity="HET",
        phase="UNKNOWN", phenotype_status="AFFECTED", source="HUMAN_REVIEW",
        metadata_json={},
    )
    db.add_all([organization, reviewer, case, analysis, variant, member, observation])
    db.commit()
    principal = SimpleNamespace(user_id=reviewer.id)
    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: variant)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)

    first = pedigree.assess_inheritance(
        analysis.id, variant.id, AssessmentInput(models=["AD"], reviewer_note="review context"),
        db, principal,
    )
    second = pedigree.assess_inheritance(
        analysis.id, variant.id, AssessmentInput(models=["AD"], reviewer_note="review context"),
        db, principal,
    )
    revised_note = pedigree.assess_inheritance(
        analysis.id, variant.id, AssessmentInput(models=["AD"], reviewer_note="revised review context"),
        db, principal,
    )

    assert first["results"][0]["id"] == second["results"][0]["id"]
    assert revised_note["results"][0]["id"] == first["results"][0]["id"]
    assert db.get(InheritanceAssessment, UUID(first["results"][0]["id"])).reviewer_note == "revised review context"
    assert db.scalar(select(func.count(InheritanceAssessment.id))) == 1
    assert db.scalar(select(func.count(Evidence.id)).where(Evidence.evidence_type == "SEGREGATION")) == 2
    audit_events = list(db.scalars(select(AuditEvent).where(
        AuditEvent.event_type == "INHERITANCE_ASSESSMENT_RECORDED"
    ).order_by(AuditEvent.occurred_at)))
    assert len(audit_events) == 2
    assert audit_events[-1].after_state["changes"][0]["before_state"]["reviewer_note"] == "review context"
    assert audit_events[-1].after_state["changes"][0]["after_state"]["reviewer_note"] == "revised review context"
    db.close()


def test_m10_supported_models_are_explicit():
    assert {normalize_model(x) for x in ["AD", "AR", "XL", "mito", "de_novo"]} == {
        "AD", "AR", "X_LINKED", "MITOCHONDRIAL", "DE_NOVO"
    }


@pytest.mark.parametrize(
    "models",
    [
        [],
        ["AD", "AR", "X_LINKED", "MITOCHONDRIAL", "DE_NOVO", "UNKNOWN", "AD"],
    ],
)
def test_m10_assessment_request_bounds_model_count(models):
    with pytest.raises(ValidationError):
        AssessmentInput(models=models)


def test_assessment_api_rejects_mitochondrial_model_outside_trial_scope(monkeypatch):
    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    monkeypatch.setattr(
        pedigree, "get_accessible_analysis",
        lambda *_args, **_kwargs: analysis,
    )
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    with pytest.raises(HTTPException) as exc:
        pedigree.assess_inheritance(
            analysis_id, variant_id, AssessmentInput(models=["MITOCHONDRIAL"]),
            SimpleNamespace(), SimpleNamespace(user_id=uuid4()),
        )
    assert exc.value.status_code == 400
    assert "outside the qualified SNV/INDEL trial scope" in exc.value.detail


def test_inheritance_assessment_binds_verified_family_matrix_fingerprint_and_stays_review_only(monkeypatch):
    analysis_id, variant_id, case_id, member_id, binding_id = (uuid4() for _ in range(5))
    principal = SimpleNamespace(user_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    matrix_fingerprint = "f" * 64
    family_matrix = {
        "schema_version": 1,
        "provenance_completeness_status": "COMPLETE",
        "matrix_fingerprint": matrix_fingerprint,
        "samples": [{
            "member_id": str(member_id),
            "is_proband": True,
            "analysis_id": str(analysis_id),
        }],
    }

    class FakeDb:
        def __init__(self):
            self.rows = [[], []]
            self.added = []
            self.committed = False

        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return self.rows.pop(0)

        def scalar(self, _query):
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    monkeypatch.setattr(
        pedigree,
        "get_family_genotype_matrix",
        lambda _case_id, body, _db, _principal: family_matrix
        if body.binding_ids == [binding_id] and body.variant_ids == [variant_id]
        else pytest.fail("Unexpected family matrix request"),
    )

    db = FakeDb()
    result = pedigree.assess_inheritance(
        analysis_id,
        variant_id,
        AssessmentInput(models=["AR"], binding_ids=[binding_id]),
        db,
        principal,
    )

    assessment = next(row for row in db.added if isinstance(row, InheritanceAssessment))
    evidence = next(row for row in db.added if isinstance(row, Evidence))
    snapshot = next(row for row in db.added if hasattr(row, "matrix_payload"))
    assert assessment.family_matrix_fingerprint == matrix_fingerprint
    assert assessment.family_matrix_snapshot_id == snapshot.id
    assert assessment.status == "REQUIRES_REVIEW"
    assert snapshot.matrix_fingerprint == matrix_fingerprint
    assert snapshot.matrix_payload == family_matrix
    assert evidence.payload["family_matrix_fingerprint"] == matrix_fingerprint
    assert evidence.payload["family_matrix_snapshot_id"] == str(snapshot.id)
    assert evidence.payload["family_matrix_binding_ids"] == [str(binding_id)]
    assert evidence.payload["manual_segregation_rows_excluded"] is True
    assert db.committed is True
    assert result["family_matrix_attached"] is True
    assert result["family_matrix_fingerprint"] == matrix_fingerprint
    assert result["results"][0]["status"] == "REQUIRES_REVIEW"
    assert "Automated inheritance compatibility is not qualified" in result["results"][0]["rationale"]


def test_inheritance_assessment_rejects_matrix_without_target_proband_binding(monkeypatch):
    analysis_id, variant_id, case_id, binding_id = (uuid4() for _ in range(4))
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)

    class FakeDb:
        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return []

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(
        pedigree,
        "get_family_genotype_matrix",
        lambda *_args: {
            "schema_version": 1,
            "provenance_completeness_status": "COMPLETE",
            "matrix_fingerprint": "e" * 64,
            "samples": [{
                "member_id": str(uuid4()),
                "is_proband": False,
                "analysis_id": str(uuid4()),
            }],
        },
    )
    with pytest.raises(HTTPException) as exc:
        pedigree.assess_inheritance(
            analysis_id,
            variant_id,
            AssessmentInput(models=["AD"], binding_ids=[binding_id]),
            FakeDb(),
            SimpleNamespace(user_id=uuid4()),
        )
    assert exc.value.status_code == 409
    assert "exactly one verified proband binding" in exc.value.detail


def test_matrix_fingerprint_replay_is_idempotent_and_new_matrix_creates_new_assessment(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    organization = Organization(id=uuid4(), name="Matrix Replay Lab")
    reviewer = User(
        id=uuid4(), organization_id=organization.id, display_name="Reviewer",
        email="matrix-reviewer@example.org", role="lab_director", status="ACTIVE",
    )
    case = Case(
        id=uuid4(), organization_id=organization.id, case_identifier="PED-MATRIX-REPLAY",
        status="ACTIVE", clinical_context={}, language="en", created_by=reviewer.id,
    )
    analysis = Analysis(
        id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1", workflow_version="1", status="REQUIRES_REVIEW",
        reference_build="GRCh38", configuration={}, created_by=reviewer.id,
    )
    variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=20,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:20:C:T:{uuid4()}", identifiers={},
    )
    db.add_all([organization, reviewer, case, analysis, variant])
    db.commit()

    fingerprint_value = {"value": "a" * 64}
    binding_id, second_binding_id, stable_member_id = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: variant)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(
        pedigree,
        "get_family_genotype_matrix",
        lambda *_args: {
            "schema_version": 1,
            "provenance_completeness_status": "COMPLETE",
            "matrix_fingerprint": fingerprint_value["value"],
            "samples": [{
                "member_id": str(stable_member_id),
                "is_proband": True,
                "analysis_id": str(analysis.id),
            }],
        },
    )

    request = AssessmentInput(
        models=["AR"], binding_ids=[binding_id, second_binding_id], reviewer_note="review",
    )
    reordered_request = AssessmentInput(
        models=["AR"], binding_ids=[second_binding_id, binding_id], reviewer_note="review",
    )
    principal = SimpleNamespace(user_id=reviewer.id)
    first = pedigree.assess_inheritance(analysis.id, variant.id, request, db, principal)
    replay = pedigree.assess_inheritance(analysis.id, variant.id, reordered_request, db, principal)
    assert first["results"][0]["id"] == replay["results"][0]["id"]
    assert first["family_matrix_fingerprint"] == replay["family_matrix_fingerprint"]
    assert db.scalar(select(func.count(Evidence.id))) == 1

    fingerprint_value["value"] = "b" * 64
    revised = pedigree.assess_inheritance(analysis.id, variant.id, request, db, principal)
    assert revised["results"][0]["id"] != first["results"][0]["id"]
    assert revised["family_matrix_fingerprint"] == "b" * 64
    assert db.scalar(select(func.count(InheritanceAssessment.id))) == 2
    assert db.scalar(select(func.count(FamilyGenotypeMatrixSnapshot.id))) == 2
    original_snapshot = db.scalar(select(FamilyGenotypeMatrixSnapshot).where(
        FamilyGenotypeMatrixSnapshot.matrix_fingerprint == "a" * 64,
    ))
    revised_snapshot = db.scalar(select(FamilyGenotypeMatrixSnapshot).where(
        FamilyGenotypeMatrixSnapshot.matrix_fingerprint == "b" * 64,
    ))
    assert original_snapshot is not None and revised_snapshot is not None
    assert original_snapshot.matrix_payload["matrix_fingerprint"] == "a" * 64
    assert revised_snapshot.matrix_payload["matrix_fingerprint"] == "b" * 64
    assert db.scalar(select(func.count(Evidence.id))) == 2
    db.close()


def test_de_novo_review_remains_unresolved_when_parent_relationship_is_only_reported(monkeypatch):
    analysis_id, variant_id, case_id, binding_id, member_id = (uuid4() for _ in range(5))
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    principal = SimpleNamespace(user_id=uuid4())
    matrix = {
        "schema_version": 1,
        "provenance_completeness_status": "COMPLETE",
        "matrix_fingerprint": "9" * 64,
        "relationships_as_recorded": [{
            "parent_member_identifier": "FATHER",
            "child_member_identifier": "PROBAND",
            "relationship_type": "PARENT_CHILD",
            "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        }],
        "samples": [{
            "member_id": str(member_id),
            "is_proband": True,
            "analysis_id": str(analysis_id),
            "identity_interpretation": "BIOLOGICAL_RELATEDNESS_NOT_ESTABLISHED",
        }],
    }

    class FakeDb:
        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return []

        def scalar(self, _query):
            return None

        def add(self, _row):
            pass

        def commit(self):
            pass

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)
    monkeypatch.setattr(pedigree, "get_family_genotype_matrix", lambda *_args: matrix)

    result = pedigree.assess_inheritance(
        analysis_id,
        variant_id,
        AssessmentInput(models=["DE_NOVO"], binding_ids=[binding_id]),
        FakeDb(),
        principal,
    )
    assert result["results"][0]["status"] == "REQUIRES_REVIEW"
    assert "relationship confidence" in result["results"][0]["rationale"]
    assert result["family_matrix_fingerprint"] == "9" * 64



def test_inheritance_assessment_rejects_family_matrix_with_incomplete_source_provenance(monkeypatch):
    analysis_id, variant_id, case_id, binding_id, member_id = (uuid4() for _ in range(5))
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    matrix = {
        "schema_version": 1,
        "provenance_completeness_status": "INCOMPLETE_REQUIRES_REVIEW",
        "matrix_fingerprint": "c" * 64,
        "samples": [{
            "member_id": str(member_id),
            "is_proband": True,
            "analysis_id": str(analysis_id),
        }],
    }

    class FakeDb:
        def get(self, _model, object_id, **_kwargs):
            return SimpleNamespace(id=object_id)

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _query):
            return []

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(pedigree, "_lock_analysis_for_pedigree", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "get_family_genotype_matrix", lambda *_args: matrix)

    with pytest.raises(HTTPException) as exc:
        pedigree.assess_inheritance(
            analysis_id,
            variant_id,
            AssessmentInput(models=["AR"], binding_ids=[binding_id]),
            FakeDb(),
            SimpleNamespace(user_id=uuid4()),
        )
    assert exc.value.status_code == 409
    assert "complete source-artifact, normalization-output and per-record digest provenance" in exc.value.detail


def test_segregation_observation_corrections_are_append_only_and_idempotent(monkeypatch):
    analysis_id, variant_id, case_id, member_id = (uuid4() for _ in range(4))
    root_id, principal_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    member = SimpleNamespace(
        id=member_id, case_id=case_id, member_identifier="PROBAND",
    )
    snapshot = {"schema_version": 1, "members": [], "relationships": []}
    root = SimpleNamespace(
        id=root_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        pedigree_member_id=member_id,
        genotype="0/1",
        zygosity="HET",
        phase="UNPHASED",
        allele_observed=None,
        phenotype_status="AFFECTED",
        source="MANUALLY_REPORTED",
        notes="initial note",
        metadata_json={"pedigree_context_snapshot": snapshot},
    )
    principal = SimpleNamespace(user_id=principal_id)

    class FakeDb:
        def __init__(self, revisions=()):
            self.revisions = list(revisions)
            self.added = []
            self.commits = 0

        def get(self, model, _identifier):
            assert model is pedigree.PedigreeMember
            return member

        def scalar(self, _query):
            return root

        def scalars(self, _query):
            return self.revisions

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.commits += 1

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        pedigree,
        "_lock_analysis_for_pedigree",
        lambda *_args: analysis,
    )
    monkeypatch.setattr(
        pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id)
    )
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "_pedigree_context_snapshot", lambda *_args: snapshot)
    monkeypatch.setattr(pedigree, "AuditService", FakeAudit)

    body = pedigree.SegregationInput(
        pedigree_member_id=member_id,
        genotype="1/1",
        zygosity="HOM_ALT",
        phase="UNPHASED",
        phenotype_status="AFFECTED",
        source="NORMALIZED_VCF",
        notes="corrected note",
        revision_reason="Corrected after review of the laboratory source document",
    )
    missing_reason_db = FakeDb()
    body_without_reason = body.model_copy(update={"revision_reason": None})
    with pytest.raises(HTTPException, match="correction reason is required"):
        pedigree.add_segregation(
            analysis_id, variant_id, body_without_reason, missing_reason_db, principal,
        )
    assert missing_reason_db.added == []
    assert missing_reason_db.commits == 0

    db = FakeDb()
    result = pedigree.add_segregation(
        analysis_id, variant_id, body, db, principal,
    )

    revision = next(
        item for item in db.added
        if isinstance(item, SegregationObservationRevision)
    )
    assert revision.root_observation_id == root_id
    assert revision.version == 2
    assert revision.revision_reason == "Corrected after review of the laboratory source document"
    assert revision.supersedes_revision_id is None
    assert revision.payload["genotype"] == "1/1"
    assert revision.payload["source"] == "MANUALLY_REPORTED"
    assert result["id"] == str(root_id)
    assert result["revision_id"] == str(revision.id)
    assert result["revision_version"] == 2
    assert root.genotype == "0/1"
    assert root.notes == "initial note"
    assert db.commits == 1

    replay_db = FakeDb(revisions=[revision])
    replay = pedigree.add_segregation(
        analysis_id, variant_id, body, replay_db, principal,
    )
    assert replay["revision_id"] == str(revision.id)
    assert replay["revision_version"] == 2
    assert replay_db.added == []
    assert replay_db.commits == 0

    revert_body = pedigree.SegregationInput(
        pedigree_member_id=member_id,
        genotype="0/1",
        zygosity="HET",
        phase="UNPHASED",
        phenotype_status="AFFECTED",
        notes="initial note",
        revision_reason="Reverted after review of the source document",
    )
    revert_db = FakeDb(revisions=[revision])
    reverted = pedigree.add_segregation(
        analysis_id, variant_id, revert_body, revert_db, principal,
    )
    revert_revision = next(
        item for item in revert_db.added
        if isinstance(item, SegregationObservationRevision)
    )
    assert revert_revision.version == 3
    assert revert_revision.supersedes_revision_id == revision.id
    assert reverted["revision_version"] == 3

