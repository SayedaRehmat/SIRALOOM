from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import Analysis
from backend.app.reporting.variant_report import build_variant_rows, render_csv, render_json
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.auth.authorization import get_accessible_analysis

router = APIRouter(tags=["variant-report"])


@router.get("/analyses/{analysis_id}/complete-variant-report")
def complete_variant_report(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal)
    rows = build_variant_rows(db, analysis_id)
    return {"analysis_id": str(analysis_id), "count": len(rows), "columns": list(rows[0].keys()) if rows else [], "variants": rows}


@router.get("/analyses/{analysis_id}/complete-variant-report.csv")
def download_complete_variant_csv(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal)
    content = render_csv(build_variant_rows(db, analysis_id))
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="siraloom_complete_variants_{analysis_id}.csv"'})


@router.get("/analyses/{analysis_id}/complete-variant-report.json")
def download_complete_variant_json(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal)
    content = render_json(build_variant_rows(db, analysis_id))
    return Response(content=content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="siraloom_complete_variants_{analysis_id}.json"'})
