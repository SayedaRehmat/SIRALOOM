from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Evidence
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.auth.authorization import get_accessible_analysis
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["evidence"])


@router.get("/analyses/{analysis_id}/evidence")
def list_analysis_evidence(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal)
    rows = db.scalars(
        select(Evidence)
        .where(Evidence.analysis_id == analysis_id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
    ).all()
    return {
        "analysis_id": str(analysis_id),
        "count": len(rows),
        "evidence": [
            {
                "evidence_id": str(row.id),
                "variant_id": str(row.variant_id),
                "type": row.evidence_type,
                "statement": row.statement,
                "direction": row.direction,
                "source": row.source_name,
                "source_version": row.source_version,
                "source_record_id": row.source_record_id,
                "observation_ids": row.observation_ids or [],
                "payload": row.payload or {},
                "created_by": {
                    "type": row.created_by_type,
                    "id": row.created_by_id,
                },
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    row = db.get(Evidence, evidence_id)
    if row:
        get_accessible_analysis(row.analysis_id, db, principal)
    if not row:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {
        "evidence_id": str(row.id),
        "analysis_id": str(row.analysis_id),
        "variant_id": str(row.variant_id),
        "type": row.evidence_type,
        "statement": row.statement,
        "direction": row.direction,
        "source": row.source_name,
        "source_version": row.source_version,
        "source_record_id": row.source_record_id,
        "observation_ids": row.observation_ids or [],
        "payload": row.payload or {},
        "created_by": {"type": row.created_by_type, "id": row.created_by_id},
        "created_at": row.created_at.isoformat(),
    }
