from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import ClinGenSpecification
from backend.app.acmg.specification_selection import ClinGenSpecificationSelector, validate_snapshot_for_automation

def test_selection_prefers_disease_specific_and_ignores_unvalidated():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            ClinGenSpecification(id=uuid4(), specification_id="GENE", version="1", provider="ClinGen", framework="ACMG/AMP", gene_scope=["TEST1"], disease_scope=[], criteria={"PM2": {}}, raw_payload={}, retrieved_at=datetime.now(timezone.utc), validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"),
            ClinGenSpecification(id=uuid4(), specification_id="DISEASE", version="2", provider="ClinGen", framework="ACMG/AMP", gene_scope=["TEST1"], disease_scope=["Disease X"], criteria={"PM2": {}}, raw_payload={}, retrieved_at=datetime.now(timezone.utc), validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"),
            ClinGenSpecification(id=uuid4(), specification_id="UNVALIDATED", version="9", provider="ClinGen", framework="ACMG/AMP", gene_scope=["TEST1"], disease_scope=["Disease X"], criteria={"PM2": {}}, raw_payload={}, retrieved_at=datetime.now(timezone.utc), validated_for_automation=False, validation_status="UNVALIDATED"),
        ])
        db.commit()
        result = ClinGenSpecificationSelector().select(db, gene="test1", disease="Disease X")
        assert result.status == "SELECTED"
        assert result.selected.specification_id == "DISEASE"

def test_selection_is_ambiguous_when_equally_specific():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for sid in ("A", "B"):
            db.add(ClinGenSpecification(id=uuid4(), specification_id=sid, version="1", provider="ClinGen", framework="ACMG/AMP", gene_scope=["TEST1"], disease_scope=["Disease X"], criteria={"PM2": {}}, raw_payload={}, retrieved_at=datetime.now(timezone.utc), validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"))
        db.commit()
        result = ClinGenSpecificationSelector().select(db, gene="TEST1", disease="Disease X")
        assert result.status == "AMBIGUOUS"
        assert result.selected is None

def test_validation_requires_structured_snapshot():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = ClinGenSpecification(id=uuid4(), specification_id="X", version="1", provider="ClinGen", framework="ACMG/AMP", gene_scope=["TEST1"], disease_scope=[], criteria={}, raw_payload={}, retrieved_at=datetime.now(timezone.utc), validated_for_automation=False, validation_status="UNVALIDATED")
        db.add(row); db.commit()
        try:
            validate_snapshot_for_automation(row, approved_by="reviewer", reason="test")
        except ValueError as exc:
            assert "structured criterion" in str(exc)
        else:
            raise AssertionError("Expected validation to fail")
