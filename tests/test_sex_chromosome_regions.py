import pytest

from backend.app.domain.sex_chromosome_regions import classify_sex_chromosome_interval


@pytest.mark.parametrize(
    ("build", "contig", "position", "expected"),
    [
        ("GRCh37", "X", 60_001, "PAR"),
        ("GRCh37", "chrX", 2_699_520, "PAR"),
        ("GRCh37", "X", 60_000, "NON_PAR"),
        ("GRCh37", "X", 2_699_521, "NON_PAR"),
        ("GRCh37", "Y", 10_001, "PAR"),
        ("GRCh37.p13", "Y", 59_363_566, "PAR"),
        ("GRCh38", "X", 10_001, "PAR"),
        ("hg38", "chrX", 2_781_479, "PAR"),
        ("GRCh38", "X", 10_000, "NON_PAR"),
        ("GRCh38", "X", 2_781_480, "NON_PAR"),
        ("GRCh38", "Y", 56_887_903, "PAR"),
        ("GRCh38", "chrY", 57_217_415, "PAR"),
        ("GRCh38", "Y", 56_887_902, "NON_PAR"),
        ("GRCh38", "1", 10_001, "NOT_SEX_CHROMOSOME"),
    ],
)
def test_build_specific_par_interval_boundaries(build, contig, position, expected):
    assert classify_sex_chromosome_interval(contig, position, position, build) == expected


def test_par_interval_crossing_boundary_is_not_silently_classified_as_par():
    assert classify_sex_chromosome_interval("X", 60_000, 60_001, "GRCh37") == "PAR_BOUNDARY_CROSSING"


@pytest.mark.parametrize(
    ("contig", "start", "end", "build"),
    [
        ("X", 0, 1, "GRCh38"),
        ("X", 2, 1, "GRCh38"),
        ("X", True, 1, "GRCh38"),
        ("X", 1, 1, "T2T-CHM13"),
        ("", 1, 1, "GRCh38"),
    ],
)
def test_par_classifier_rejects_invalid_or_unsupported_inputs(contig, start, end, build):
    with pytest.raises(ValueError):
        classify_sex_chromosome_interval(contig, start, end, build)


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        ("GRCh37", "GRCh37"),
        ("GRCh37.p13", "GRCh37"),
        ("hg19", "GRCh37"),
        ("GRCh38", "GRCh38"),
        ("GRCh38.p14", "GRCh38"),
        ("hg38", "GRCh38"),
    ],
)
def test_human_reference_build_aliases_are_normalized(build, expected):
    from backend.app.domain.sex_chromosome_regions import normalize_human_reference_build

    assert normalize_human_reference_build(build) == expected
