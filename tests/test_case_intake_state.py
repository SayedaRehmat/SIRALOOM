import pytest

from backend.app.domain.case_intake import case_status_after_vcf_upload


@pytest.mark.parametrize(
    ("current", "valid", "has_vcf", "expected"),
    [
        ("DRAFT", True, True, "READY_FOR_ANALYSIS"),
        ("READY_FOR_ANALYSIS", False, True, "INVALID"),
        ("INVALID", True, True, "READY_FOR_ANALYSIS"),
        ("COMPLETE", True, True, "COMPLETE"),
        ("ARCHIVED", False, True, "ARCHIVED"),
        ("SPECIMEN_REGISTERED", False, False, "SPECIMEN_REGISTERED"),
    ],
)
def test_vcf_upload_status_respects_persisted_inputs_and_lifecycle(
    current, valid, has_vcf, expected
):
    assert case_status_after_vcf_upload(
        current,
        has_valid_vcf=valid,
        has_vcf=has_vcf,
    ) == expected


def test_site_only_vcf_does_not_mark_case_ready_or_invalid():
    assert case_status_after_vcf_upload(
        "DRAFT",
        has_valid_vcf=False,
        has_vcf=True,
        has_site_only_vcf=True,
    ) == "ARTIFACT_UPLOADED"
