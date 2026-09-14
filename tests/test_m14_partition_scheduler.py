from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import AnalysisPartition
from backend.app.partition_scheduler import PartitionScheduler, configure_partition
from backend.app.infrastructure.db.models import Analysis, Case, Organization, User


def make_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'m14.db'}")
    Base.metadata.create_all(engine)
    return engine


def seed_analysis(db):
    oid, uid, cid, aid = uuid4(), uuid4(), uuid4(), uuid4()
    db.add(Organization(id=oid, name="Org", external_identifier=None))
    db.add(User(id=uid, organization_id=oid, display_name="u", role="ADMIN", status="ACTIVE"))
    db.add(Case(id=cid, organization_id=oid, case_identifier="C1", status="READY", created_by=uid))
    db.add(Analysis(id=aid, case_id=cid, analysis_type="GERMLINE", workflow_id="w", workflow_version="1", status="RUNNING", reference_build="GRCh38", configuration={}))
    db.commit()
    return aid


def test_scheduler_enforces_cpu_and_memory_capacity(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        aid = seed_analysis(db)
        for i in range(3):
            p = AnalysisPartition(id=uuid4(), analysis_id=aid, step_id="annotate", partition_key=str(i), ordinal=i, record_start=i*10, record_end=i*10+10, variant_count=10, status="READY", metadata_json={})
            configure_partition(p, "STANDARD")
            db.add(p)
        db.commit()
        scheduler = PartitionScheduler(db, cpu_capacity=2, memory_mb=2048, lease_seconds=60)
        a = scheduler.claim_next(aid, "annotate", "w1")
        b = scheduler.claim_next(aid, "annotate", "w2")
        c = scheduler.claim_next(aid, "annotate", "w3")
        assert a and b
        assert c is None
        cap = scheduler.capacity()
        assert cap["cpu_used"] == 2.0
        assert cap["memory_mb_used"] == 2048


def test_scheduler_lease_recovery_and_retry_limit(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        aid = seed_analysis(db)
        p = AnalysisPartition(id=uuid4(), analysis_id=aid, step_id="annotate", partition_key="0", ordinal=0, record_start=0, record_end=10, variant_count=10, status="READY", metadata_json={})
        configure_partition(p, "STANDARD")
        db.add(p); db.commit()
        scheduler = PartitionScheduler(db, cpu_capacity=1, memory_mb=1024, lease_seconds=1)
        claimed = scheduler.claim_next(aid, "annotate", "w1")
        assert claimed and claimed.attempt == 1
        claimed.lease_expires_at = claimed.lease_expires_at - timedelta(seconds=10)
        db.commit()
        recovered = scheduler.claim_next(aid, "annotate", "w2")
        assert recovered and recovered.lease_owner == "w2" and recovered.attempt == 2
        scheduler.fail(recovered.id, "w2", error_code="TEMP", error_message="retry")
        assert db.get(AnalysisPartition, recovered.id).status == "READY"
