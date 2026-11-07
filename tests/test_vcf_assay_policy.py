from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.domain.schemas import AnalysisCreate
from backend.app.domain.vcf_validation import StrictVCFValidationError
from backend.app.workflows.variant import _base_modification_strandedness_policy


@pytest.mark.parametrize("policy", ["stranded", "unstranded"])
def test_analysis_create_accepts_explicit_base_modification_assay_policy(policy: str):
    payload = AnalysisCreate(
        input_artifact_id=uuid4(),
        base_modification_strandedness=policy,
    )
    assert payload.base_modification_strandedness == policy


def test_analysis_create_defaults_assay_policy_to_unknown_not_inferred():
    payload = AnalysisCreate(input_artifact_id=uuid4())
    assert payload.base_modification_strandedness is None


def test_analysis_create_rejects_unknown_base_modification_assay_policy():
    with pytest.raises(ValidationError):
        AnalysisCreate(
            input_artifact_id=uuid4(),
            base_modification_strandedness="guess-from-values",
        )


@pytest.mark.parametrize("policy", [None, "stranded", "unstranded"])
def test_worker_reads_persisted_base_modification_assay_policy(policy: str | None):
    analysis = SimpleNamespace(
        configuration=(
            {"base_modification_strandedness": policy}
            if policy is not None
            else {}
        )
    )
    assert _base_modification_strandedness_policy(analysis) == policy


@pytest.mark.parametrize("invalid_policy", ["infer", [], {}])
def test_worker_rejects_invalid_persisted_base_modification_assay_policy(invalid_policy):
    analysis = SimpleNamespace(
        configuration={"base_modification_strandedness": invalid_policy}
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        _base_modification_strandedness_policy(analysis)
    assert exc.value.code == "VCF_BASE_MODIFICATION_POLICY_INVALID"
