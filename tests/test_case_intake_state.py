import pytest

from backend.app.domain.case_intake import case_status_after_vcf_upload


@pytest.mark.parametrize(
    ("current", "valid", "analysis_ready", "has_vcf", "expected"),
    [
        ("DRAFT", True, True, True, "READY_FOR_ANALYSIS"),
        ("DRAFT", True, False, True, "ARTIFACT_UPLOADED"),
        ("READY_FOR_ANALYSIS", False, False, True, "INVALID"),
        ("INVALID", True, True, True, "READY_FOR_ANALYSIS"),
        ("COMPLETE", True, True, True, "COMPLETE"),
        ("ARCHIVED", False, False, True, "ARCHIVED"),
        ("SPECIMEN_REGISTERED", False, False, False, "SPECIMEN_REGISTERED"),
    ],
)
def test_vcf_upload_status_respects_persisted_inputs_and_lifecycle(
    current, valid, analysis_ready, has_vcf, expected
):
    assert case_status_after_vcf_upload(
        current,
        has_valid_vcf=valid,
        has_analysis_ready_vcf=analysis_ready,
        has_vcf=has_vcf,
    ) == expected


def test_site_only_vcf_does_not_mark_case_ready_or_invalid():
    assert case_status_after_vcf_upload(
        "DRAFT",
        has_valid_vcf=False,
        has_analysis_ready_vcf=False,
        has_vcf=True,
        has_site_only_vcf=True,
    ) == "ARTIFACT_UPLOADED"


def test_structurally_valid_sample_vcf_is_not_implicitly_analysis_ready():
    assert case_status_after_vcf_upload(
        "DRAFT",
        has_valid_vcf=True,
        has_analysis_ready_vcf=False,
        has_vcf=True,
    ) == "ARTIFACT_UPLOADED"


def test_sample_vcf_requires_explicit_analysis_ready_decision():
    assert case_status_after_vcf_upload(
        "ARTIFACT_UPLOADED",
        has_valid_vcf=True,
        has_analysis_ready_vcf=True,
        has_vcf=True,
    ) == "READY_FOR_ANALYSIS"
