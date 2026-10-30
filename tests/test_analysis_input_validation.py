from types import SimpleNamespace

import pytest

from backend.app.application.analysis import validate_analysis_input_artifact


@pytest.mark.parametrize("build", ["GRCh37", "GRCh38", "hg19", "hg38"])
def test_analysis_accepts_valid_primary_vcf_on_matching_supported_build(build):
    canonical = {"hg19": "GRCh37", "hg38": "GRCh38"}.get(build, build)
    artifact = SimpleNamespace(
        artifact_type="VCF",
        validation_status="VALID",
        genome_build=build,
        metadata_json={"validation": {"sample_names": ["PROBAND"]}},
    )

    validate_analysis_input_artifact(artifact, canonical)


@pytest.mark.parametrize(
    ("artifact_type", "validation_status", "artifact_build", "requested_build", "message"),
    [
        ("VCF_INDEX_TBI", "VALID", "GRCh38", "GRCh38", "primary VCF"),
        ("VCF", "INVALID", "GRCh38", "GRCh38", "pass ingestion validation"),
        ("VCF", "VALID", "GRCh37", "GRCh38", "must match"),
        ("VCF", "VALID", None, "GRCh38", "declare a supported"),
        ("VCF", "VALID", "GRCh38", "GRCh39", "must be GRCh37 or GRCh38"),
    ],
)
def test_analysis_rejects_unusable_input_artifact(
    artifact_type, validation_status, artifact_build, requested_build, message
):
    artifact = SimpleNamespace(
        artifact_type=artifact_type,
        validation_status=validation_status,
        genome_build=artifact_build,
        metadata_json={"validation": {"sample_names": ["PROBAND"]}},
    )

    with pytest.raises(ValueError, match=message):
        validate_analysis_input_artifact(artifact, requested_build)


@pytest.mark.parametrize("sample_names", [[], None])
def test_analysis_rejects_vcfs_without_sample_genotypes(sample_names):
    artifact = SimpleNamespace(
        artifact_type="VCF",
        validation_status="VALID",
        genome_build="GRCh38",
        metadata_json={"validation": {"sample_names": sample_names}},
    )

    with pytest.raises(ValueError, match="Sites-only VCFs contain no sample genotypes"):
        validate_analysis_input_artifact(artifact, "GRCh38")


def test_analysis_requires_exact_explicit_specimen_sample_mapping():
    artifact = SimpleNamespace(
        artifact_type="VCF",
        validation_status="VALID",
        genome_build="GRCh38",
        metadata_json={"validation": {"sample_names": ["VCF-PATIENT-01"]}},
    )

    validate_analysis_input_artifact(artifact, "GRCh38", "VCF-PATIENT-01")
    with pytest.raises(ValueError, match="not present in the input callset"):
        validate_analysis_input_artifact(artifact, "GRCh38", "VCF-FAMILY-02")



def test_analysis_allows_explicitly_mapped_sample_from_multisample_vcf():
    artifact = SimpleNamespace(
        artifact_type="VCF",
        validation_status="VALID",
        genome_build="GRCh38",
        metadata_json={"validation": {"sample_names": ["PROBAND", "MOTHER", "FATHER"]}},
    )

    validate_analysis_input_artifact(artifact, "GRCh38", "PROBAND")

    with pytest.raises(ValueError, match="Multisample VCF analysis requires"):
        validate_analysis_input_artifact(artifact, "GRCh38")
