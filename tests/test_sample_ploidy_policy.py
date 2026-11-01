from uuid import uuid4

import pytest

from backend.app.domain.sample_ploidy_policy import (
    PloidyPolicyValidationError,
    parse_caller_ploidy_policy,
    parse_sample_ploidy_evidence,
    resolve_expected_gt_ploidy,
)


SPECIMEN_ID = str(uuid4())
_DEFAULT = object()


def sample_evidence(**overrides):
    payload = {
        "schema_version": 1,
        "specimen_id": SPECIMEN_ID,
        "reference_build": "GRCh38",
        "status": "VERIFIED",
        "region_copy_number": {"PAR": 2, "X_NON_PAR": 1, "Y_NON_PAR": 1},
        "source_type": "CYTOGENETIC_REPORT",
        "evidence_reference": "artifact:sha256:" + "a" * 64,
        "reviewed_by": "reviewer-123",
        "reviewed_at": "2026-10-31T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def caller_policy(**overrides):
    payload = {
        "schema_version": 1,
        "caller_id": "validated-caller",
        "caller_version": "4.2.1",
        "assay_id": "constitutional-exome-v3",
        "policy_version": "1.0.0",
        "reference_build": "GRCh38",
        "status": "QUALIFIED",
        "validation_evidence_reference": "validation-record-456",
        "qualified_by": "lab-director-17",
        "qualified_at": "2026-10-31T11:00:00+00:00",
        "region_copy_number_to_gt_ploidy": {
            "PAR": {"2": 2},
            "X_NON_PAR": {"1": 1, "2": 2},
            "Y_NON_PAR": {"0": "NOT_CALLABLE", "1": 1},
        },
    }
    payload.update(overrides)
    return payload


def resolve(evidence=_DEFAULT, policy=_DEFAULT, **kwargs):
    return resolve_expected_gt_ploidy(
        sample_evidence() if evidence is _DEFAULT else evidence,
        caller_policy() if policy is _DEFAULT else policy,
        specimen_id=kwargs.get("specimen_id", SPECIMEN_ID),
        caller_id=kwargs.get("caller_id", "validated-caller"),
        caller_version=kwargs.get("caller_version", "4.2.1"),
        assay_id=kwargs.get("assay_id", "constitutional-exome-v3"),
        reference_build=kwargs.get("reference_build", "GRCh38"),
        region=kwargs.get("region", "X_NON_PAR"),
    )


def test_verified_specimen_evidence_and_exact_qualified_caller_policy_resolve_haploid_gt():
    result = resolve(region="X_NON_PAR")
    assert result.status == "RESOLVED_CALLABLE"
    assert result.expected_gt_ploidy == 1
    assert result.copy_number == 1
    assert result.reason_code == "VERIFIED_SAMPLE_EVIDENCE_AND_QUALIFIED_CALLER_POLICY_MATCH"


def test_par_uses_explicit_total_region_copy_number_and_caller_policy():
    result = resolve(region="PAR")
    assert result.status == "RESOLVED_CALLABLE"
    assert result.copy_number == 2
    assert result.expected_gt_ploidy == 2


def test_zero_copy_region_requires_caller_policy_and_resolves_as_not_callable():
    evidence = sample_evidence(region_copy_number={"Y_NON_PAR": 0})
    result = resolve(evidence=evidence, region="Y_NON_PAR")
    assert result.status == "RESOLVED_NOT_CALLABLE"
    assert result.expected_gt_ploidy is None


@pytest.mark.parametrize(
    ("evidence", "policy", "kwargs", "reason"),
    [
        (None, caller_policy(), {}, "SAMPLE_PLOIDY_EVIDENCE_MISSING"),
        (sample_evidence(), None, {}, "CALLER_PLOIDY_POLICY_MISSING"),
        (sample_evidence(status="UNVERIFIED"), caller_policy(), {}, "SAMPLE_PLOIDY_EVIDENCE_NOT_VERIFIED"),
        (sample_evidence(status="CONFLICTED"), caller_policy(), {}, "SAMPLE_PLOIDY_EVIDENCE_NOT_VERIFIED"),
        (sample_evidence(status="MOSAIC_OR_COMPLEX"), caller_policy(), {}, "SAMPLE_PLOIDY_EVIDENCE_NOT_VERIFIED"),
        (sample_evidence(reference_build="GRCh37"), caller_policy(), {}, "SAMPLE_EVIDENCE_REFERENCE_BUILD_MISMATCH"),
        (sample_evidence(), caller_policy(status="DRAFT"), {}, "CALLER_PLOIDY_POLICY_NOT_QUALIFIED"),
        (sample_evidence(), caller_policy(caller_version="4.2.0"), {}, "CALLER_ASSAY_VERSION_POLICY_MISMATCH"),
        (sample_evidence(), caller_policy(reference_build="GRCh37"), {}, "CALLER_POLICY_REFERENCE_BUILD_MISMATCH"),
        (sample_evidence(), caller_policy(region_copy_number_to_gt_ploidy={"X_NON_PAR": {"2": 2}}), {}, "CALLER_POLICY_COPY_NUMBER_UNSUPPORTED"),
        (sample_evidence(), caller_policy(region_copy_number_to_gt_ploidy={"PAR": {"2": 2}}), {}, "CALLER_POLICY_REGION_UNSUPPORTED"),
        (sample_evidence(region_copy_number={"PAR": 2}), caller_policy(), {"region": "X_NON_PAR"}, "SAMPLE_REGION_COPY_NUMBER_MISSING"),
        (sample_evidence(), caller_policy(), {"specimen_id": str(uuid4())}, "SPECIMEN_ID_MISMATCH"),
    ],
)
def test_missing_unverified_conflicted_or_mismatched_evidence_fails_closed(evidence, policy, kwargs, reason):
    assert resolve(evidence=evidence, policy=policy, **kwargs).reason_code == reason


@pytest.mark.parametrize(
    "payload",
    [
        sample_evidence(schema_version=2),
        sample_evidence(schema_version=True),
        sample_evidence(specimen_id="not-a-uuid"),
        sample_evidence(reference_build="T2T-CHM13"),
        sample_evidence(region_copy_number={"X_NON_PAR": -1}),
        sample_evidence(region_copy_number={"X_NON_PAR": True}),
        sample_evidence(region_copy_number={"MT": 2}),
        sample_evidence(source_type=None),
        sample_evidence(evidence_reference=None),
        sample_evidence(reviewed_by=None),
        sample_evidence(reviewed_at="2026-10-31T10:00:00"),
    ],
)
def test_invalid_verified_sample_evidence_is_rejected(payload):
    with pytest.raises(PloidyPolicyValidationError):
        parse_sample_ploidy_evidence(payload)


@pytest.mark.parametrize(
    "payload",
    [
        caller_policy(schema_version=2),
        caller_policy(caller_id=""),
        caller_policy(status="QUALIFIED", qualified_by=None),
        caller_policy(status="QUALIFIED", validation_evidence_reference=None),
        caller_policy(status="QUALIFIED", qualified_at="2026-10-31T11:00:00"),
        caller_policy(region_copy_number_to_gt_ploidy={"X_NON_PAR": {"-1": 2}}),
        caller_policy(region_copy_number_to_gt_ploidy={"X_NON_PAR": {"1": 0}}),
        caller_policy(region_copy_number_to_gt_ploidy={"X_NON_PAR": {"1": True}}),
        caller_policy(region_copy_number_to_gt_ploidy={"MT": {"2": 2}}),
    ],
)
def test_invalid_caller_policy_is_rejected(payload):
    with pytest.raises(PloidyPolicyValidationError):
        parse_caller_ploidy_policy(payload)


@pytest.mark.parametrize("forbidden_field", ["sex", "karyotype", "observed_gt", "allele_balance"])
def test_pedigree_sex_karyotype_and_observed_calls_are_not_accepted_as_ploidy_evidence(forbidden_field):
    # The versioned evidence contract accepts only explicit, reviewed region
    # copy-number assertions; no inference source is silently consumed.
    payload = sample_evidence()
    payload[forbidden_field] = "not-an-input"
    with pytest.raises(PloidyPolicyValidationError, match="Unsupported sample ploidy evidence fields"):
        parse_sample_ploidy_evidence(payload)
