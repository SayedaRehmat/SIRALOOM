from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService, SpecificationBindingError
from backend.app.acmg.specification_selection import SelectionResult, SpecificationCandidate
from backend.app.infrastructure.db.models import Resource


class _Selector:
    def __init__(self):
        self.kwargs = None

    def select(self, db, **kwargs):
        self.kwargs = kwargs
        return SelectionResult(
            status="NOT_FOUND",
            selected=None,
            candidates=(),
            reason="No exact specification matched.",
        )


def _resource(metadata=None, provider="CLINGEN", resource_type="ACMG_RULE_SPECIFICATION"):
    return SimpleNamespace(
        id=uuid4(),
        provider=provider,
        resource_type=resource_type,
        metadata_json=metadata or {},
    )


def test_profile_bound_acmg_resource_requires_explicit_specification_identity():
    selector = _Selector()
    service = ACMGSpecificationAssessmentService(selector=selector)

    with pytest.raises(SpecificationBindingError, match="specification_id and specification_version"):
        service.bind(
            SimpleNamespace(),
            gene="GENE1",
            specification_resource=_resource(),
        )


def test_profile_bound_acmg_resource_filters_selector_to_exact_identity():
    selector = _Selector()
    service = ACMGSpecificationAssessmentService(selector=selector)

    binding, row = service.bind(
        SimpleNamespace(),
        gene="GENE1",
        disease="Disease",
        specification_resource=_resource(
            {"specification_id": "VCEP-GENE1", "specification_version": "2.1.0"}
        ),
    )

    assert binding.status == "NOT_FOUND"
    assert row is None
    assert selector.kwargs == {
        "gene": "GENE1",
        "disease": "Disease",
        "specification_id": "VCEP-GENE1",
        "specification_version": "2.1.0",
    }


def test_profile_bound_acmg_resource_rejects_non_clingen_provider():
    service = ACMGSpecificationAssessmentService(selector=_Selector())

    with pytest.raises(SpecificationBindingError, match="not ClinGen"):
        service.bind(
            SimpleNamespace(),
            gene="GENE1",
            specification_resource=_resource(
                {"specification_id": "VCEP-GENE1", "specification_version": "2.1.0"},
                provider="OTHER",
            ),
        )
