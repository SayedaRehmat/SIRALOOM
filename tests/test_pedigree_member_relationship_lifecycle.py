from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import pedigree
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Case,
    Organization,
    PedigreeMember,
    PedigreeMemberRevision,
    PedigreeRelationship,
    PedigreeRelationshipRevision,
    User,
)


def _clinical_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    organization = Organization(id=uuid4(), name="Pedigree Lifecycle Test Lab")
    actor = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Clinical Reviewer",
        email=f"reviewer-{uuid4()}@example.org",
        role="lab_director",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier=f"PED-LIFECYCLE-{uuid4()}",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=actor.id,
    )
    db.add_all([organization, actor, case])
    db.commit()
    return db, actor, case


def test_member_correction_is_projected_without_mutating_original_record():
    db, actor, case = _clinical_db()
    member = PedigreeMember(
        id=uuid4(),
        case_id=case.id,
        member_identifier="FATHER",
        relationship_to_proband="father",
        sex="MALE",
        affected_status="UNKNOWN",
        is_proband=False,
        sampled=False,
        metadata_json={},
    )
    db.add(member)
    db.flush()
    revision = PedigreeMemberRevision(
        id=uuid4(),
        case_id=case.id,
        member_id=member.id,
        version=2,
        revision_type="CORRECTED",
        reason="Corrected after review of the signed family history",
        payload={"affected_status": "AFFECTED", "is_proband": False},
        revision_fingerprint="a" * 64,
        recorded_by=actor.id,
    )
    db.add(revision)
    db.commit()

    state = pedigree._current_member_state(db, member)
    assert state["affected_status"] == "AFFECTED"
    assert state["revision_version"] == 2
    assert state["revision_type"] == "CORRECTED"
    assert state["status"] == "ACTIVE"
    assert member.affected_status == "UNKNOWN"
    db.close()


def test_retracted_relationship_is_excluded_from_effective_pedigree():
    db, actor, case = _clinical_db()
    parent = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="PARENT",
        affected_status="UNKNOWN", is_proband=False, sampled=False, metadata_json={},
    )
    child = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="CHILD",
        affected_status="AFFECTED", is_proband=True, sampled=False, metadata_json={},
    )
    db.add_all([parent, child])
    db.flush()
    relationship = PedigreeRelationship(
        id=uuid4(), case_id=case.id, parent_member_id=parent.id,
        child_member_id=child.id, relationship_type="PARENT_CHILD", metadata_json={},
    )
    db.add(relationship)
    db.flush()
    revision = PedigreeRelationshipRevision(
        id=uuid4(), case_id=case.id, relationship_id=relationship.id,
        version=2, revision_type="RETRACTED",
        reason="Relationship was entered against the wrong family member",
        payload={}, revision_fingerprint="b" * 64, recorded_by=actor.id,
    )
    db.add(revision)
    db.commit()

    members, relationships, _, relationship_history = pedigree._current_pedigree(db, case.id)
    assert len(members) == 2
    assert relationships == []
    assert relationship_history[0]["status"] == "RETRACTED"
    assert relationship.parent_member_id == parent.id
    db.close()


def test_retracted_member_is_excluded_from_effective_pedigree():
    db, actor, case = _clinical_db()
    proband = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="PROBAND",
        affected_status="AFFECTED", is_proband=True, sampled=False, metadata_json={},
    )
    other = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="OTHER",
        affected_status="UNKNOWN", is_proband=False, sampled=False, metadata_json={},
    )
    db.add_all([proband, other])
    db.flush()
    revision = PedigreeMemberRevision(
        id=uuid4(), case_id=case.id, member_id=other.id,
        version=2, revision_type="RETRACTED",
        reason="Duplicate family member record",
        payload={}, revision_fingerprint="c" * 64, recorded_by=actor.id,
    )
    db.add(revision)
    db.commit()

    members, _, member_history, _ = pedigree._current_pedigree(db, case.id)
    assert [member["member_identifier"] for member in members] == ["PROBAND"]
    assert len(member_history) == 2
    assert next(item for item in member_history if item["id"] == str(other.id))["status"] == "RETRACTED"
    db.close()


def test_corrected_proband_projection_enforces_single_active_proband():
    db, actor, case = _clinical_db()
    first = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="FIRST",
        affected_status="AFFECTED", is_proband=True, sampled=False, metadata_json={},
    )
    second = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="SECOND",
        affected_status="UNKNOWN", is_proband=False, sampled=False, metadata_json={},
    )
    db.add_all([first, second])
    db.flush()
    revision = PedigreeMemberRevision(
        id=uuid4(), case_id=case.id, member_id=second.id,
        version=2, revision_type="CORRECTED",
        reason="Proband designation corrected from the signed requisition",
        payload={"is_proband": True},
        revision_fingerprint="d" * 64, recorded_by=actor.id,
    )
    db.add(revision)
    db.commit()

    members, _, _, _ = pedigree._current_pedigree(db, case.id)
    try:
        pedigree._validate_projected_proband(members)
    except Exception as error:
        assert getattr(error, "status_code", None) == 409
    else:
        raise AssertionError("Two active probands must be rejected")
    db.close()
