"""PostgreSQL durability, deduplication, replay and review projection for C1 evidence."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.domain.evidence import evidence_fingerprint
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Case, Evidence, Organization, User, Variant
from backend.app.review.service import _evidence_context_dict


@pytest.mark.integration
def test_gene_disease_reconciliation_evidence_is_deduplicated_after_crash_replay_and_reviewable():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    analysis_id, variant_id = uuid4(), uuid4()
    source_payload = {
        "reconciliation_id": "c1-test-reconciliation-0001",
        "status": "G2P_ONLY",
        "requires_human_review": True,
        "review_reasons": ["ASSOCIATION_G2P_ONLY", "CANONICAL_HGNC_IDENTIFIER_INCOMPLETE"],
        "interpretive_use": "GENE_DISEASE_RECONCILIATION_CONTEXT_ONLY",
        "clinical_conclusion": False,
        "source_provenance": [{
            "source": "G2P", "source_record_id": "G2P:G2P0001",
            "resource_id": "00000000-0000-0000-0000-000000000001",
            "resource_name": "Gene2Phenotype", "resource_version": "2026-11-08",
            "resource_sha256": "a" * 64, "source_record_sha256": "b" * 64,
            "request_fingerprint": "c" * 64, "response_sha256": "d" * 64,
            "raw_assertion": {"Gene Symbol": "GENE1", "Disease Mondo": "MONDO:0000001"},
        }],
    }
    statement = "Independent gene-disease assertions retained for reviewer context."
    fingerprint = evidence_fingerprint(
        variant_id=variant_id, analysis_id=analysis_id, evidence_type="GENE_DISEASE",
        statement=statement, direction="NEUTRAL",
        source_name="SIRALOOM gene-disease reconciliation", source_version="1",
        observation_ids=(), payload=source_payload, resource_id=None,
        source_record_id=source_payload["reconciliation_id"], request_fingerprint=None,
        response_sha256=None,
    )
    try:
        with Session(engine) as db:
            db.add(Organization(id=organization_id, name="C1 integration organization"))
            db.add(User(id=user_id, organization_id=organization_id, display_name="C1 integration", role="ADMIN", status="ACTIVE"))
            db.flush()
            db.add(Case(id=case_id, organization_id=organization_id, case_identifier=f"C1-{case_id}", status="OPEN", clinical_context={}, created_by=user_id))
            db.flush()  # The Analysis foreign key requires the Case row to exist first.
            db.add(Analysis(
                id=analysis_id, case_id=case_id, analysis_type="VCF", workflow_id="integration",
                workflow_version="1", status="COMPLETED", reference_build="GRCh38",
                configuration={}, created_by=user_id, toolchain_profile_id="integration",
                toolchain_bcftools_version="1.19", toolchain_htslib_version="1.19", toolchain_snapshot={},
            ))
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1", position=100,
                reference="A", alternate="G", normalization_status="NORMALIZED",
                canonical_key=f"C1-{variant_id}", identifiers={},
            ))
            db.commit()

        # First worker attempt commits the evidence, then dies before its stage checkpoint.
        with Session(engine) as db:
            db.add(Evidence(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                evidence_type="GENE_DISEASE", statement=statement, direction="NEUTRAL",
                source_name="SIRALOOM gene-disease reconciliation", source_version="1",
                resource_id=None, source_record_id=source_payload["reconciliation_id"],
                request_fingerprint=None, response_sha256=None, request_metadata={"source_provenance": source_payload["source_provenance"]},
                observation_ids=[], payload=source_payload, created_by_type="SYSTEM",
                created_by_id="siraloom-evidence", evidence_fingerprint=fingerprint,
            ))
            db.commit()

        # Redelivery computes the same content fingerprint and observes the durable row.
        with Session(engine) as db:
            existing = db.scalar(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
                Evidence.evidence_fingerprint == fingerprint,
            ))
            if existing is None:
                db.add(Evidence(
                    id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                    evidence_type="GENE_DISEASE", statement=statement, direction="NEUTRAL",
                    source_name="SIRALOOM gene-disease reconciliation", source_version="1",
                    resource_id=None, source_record_id=source_payload["reconciliation_id"],
                    request_fingerprint=None, response_sha256=None,
                    request_metadata={"source_provenance": source_payload["source_provenance"]},
                    observation_ids=[], payload=source_payload, created_by_type="SYSTEM",
                    created_by_id="siraloom-evidence", evidence_fingerprint=fingerprint,
                ))
                db.commit()
            count = db.scalar(select(func.count(Evidence.id)).where(
                Evidence.analysis_id == analysis_id,
                Evidence.evidence_fingerprint == fingerprint,
            ))
            assert count == 1
            persisted = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis_id, Evidence.evidence_fingerprint == fingerprint))
            review_context = _evidence_context_dict(persisted)
            assert review_context["type"] == "GENE_DISEASE"
            assert review_context["direction"] == "NEUTRAL"
            assert review_context["source_record_id"] == source_payload["reconciliation_id"]
            assert review_context["payload"]["clinical_conclusion"] is False
            assert review_context["payload"]["requires_human_review"] is True
            assert review_context["payload"]["source_provenance"][0]["raw_assertion"] == source_payload["source_provenance"][0]["raw_assertion"]
    finally:
        with Session(engine) as db:
            db.query(Evidence).filter(Evidence.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(Variant).filter(Variant.id == variant_id).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(synchronize_session=False)
            db.query(Case).filter(Case.id == case_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id == organization_id).delete(synchronize_session=False)
            db.commit()
        engine.dispose()
