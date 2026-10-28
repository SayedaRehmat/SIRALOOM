from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
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
    InheritanceAssessment,
    Organization,
    PedigreeMember,
    SegregationObservation,
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
        parent_member_id=father_id, child_member_id=proband_id,
        relationship_type="PARENT_CHILD", metadata_json={},
    )

    class FakeDb:
        def __init__(self):
            self.rows = [[proband, father], [relationship]]

        def scalars(self, _query):
            return self.rows.pop(0)

    snapshot = pedigree._pedigree_context_snapshot(FakeDb(), case_id)

    assert snapshot["schema_version"] == 1
    assert [member["member_identifier"] for member in snapshot["members"]] == [
        "father", "proband"
    ]
    assert snapshot["relationships"] == [{
        "parent_member_identifier": "father",
        "child_member_identifier": "proband",
        "relationship_type": "PARENT_CHILD",
        "metadata": {},
    }]


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
    assert lock_permissions == ["review"]
    assert "score" not in result["results"][0]
    assert "score" not in result
    assert db.committed is True
    assessment = next(row for row in db.added if hasattr(row, "observation_fingerprint"))
    evidence = next(row for row in db.added if getattr(row, "evidence_type", None) == "SEGREGATION")
    assert assessment.score is None
    assert evidence.source_version == "M11_OBSERVATIONS_ONLY"
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
    obs = [FamilyObservation("PROBAND", "UNKNOWN", "AFFECTED", "0/1", "HET")]
    observation_fingerprint = fingerprint(obs)
    assessment = InheritanceAssessment(
        id=uuid4(), analysis_id=analysis_id, variant_id=variant_id, model="AD",
        status="REQUIRES_REVIEW", score=None,
        rationale=assess_model("AD", obs)["rationale"],
        observation_fingerprint=observation_fingerprint, reviewer_note="review context",
        created_by=str(principal.user_id),
    )
    payload = {
        "model": "AD", "status": "REQUIRES_REVIEW", "observations_available": 1,
        "observation_fingerprint": observation_fingerprint,
        "reviewer_note": "review context", "interpretation": "REQUIRES_HUMAN_REVIEW",
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
