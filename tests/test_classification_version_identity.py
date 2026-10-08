from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Classification, Variant


def test_classification_version_identity_is_unique():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        analysis = Analysis(
            id=uuid4(), case_id=uuid4(), analysis_type="VARIANT_INTERPRETATION",
            workflow_id="variant-v1", workflow_version="1.0", status="RUNNING",
            reference_build="GRCh38", configuration={}
        )
        variant = Variant(
            id=uuid4(), genome_build="GRCh38", chromosome="1", position=100,
            reference="A", alternate="G", normalization_status="NORMALIZED",
            canonical_key="GRCh38:1:100:A:G", identifiers={}
        )
        db.add_all([analysis, variant])
        db.commit()

        db.add_all([
            Classification(
                id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                framework_name="ACMG/AMP", framework_version="2015",
                result="VUS", criterion_ids=[], metadata_json={},
                state="PROPOSED", review_status="PENDING", version=1
            ),
            Classification(
                id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                framework_name="ACMG/AMP", framework_version="2015",
                result="LIKELY_PATHOGENIC", criterion_ids=[], metadata_json={},
                state="PROPOSED", review_status="PENDING", version=1
            ),
        ])
        with pytest.raises(IntegrityError):
            db.commit()
