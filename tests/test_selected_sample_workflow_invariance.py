"""Regression coverage for specimen-selected multisample VCF genotype provenance.

The selected specimen sample must be resolved by its exact VCF sample name, not
by column position, first-sample fallback, or aggregation across family members.
The same selected call must survive the workflow's normalized-partition snapshot.
"""
from __future__ import annotations

from itertools import permutations
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.domain.normalization import iter_normalized_vcf
from backend.app.domain.vcf import VCFValidationError


SAMPLE_CALLS = {
    "FATHER": ("0/1:30", "0/0:20"),
    "PROBAND": ("1/1:40", "0/0:20"),
    "MOTHER": ("0/0:20", "0/1:25"),
}

EXPECTED = {
    "FATHER": (100, "0/1", 1),
    "PROBAND": (100, "1/1", 2),
    "MOTHER": (200, "0/1", 1),
}


def _write_family_vcf(path: Path, sample_order: tuple[str, ...]) -> None:
    sample_values = []
    for sample_name in sample_order:
        first, second = SAMPLE_CALLS[sample_name]
        sample_values.append((first, second))

    first_record = "\t".join(values[0] for values in sample_values)
    second_record = "\t".join(values[1] for values in sample_values)
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
        + "\t".join(sample_order)
        + "\n"
        + "1\t100\t.\tA\tC\t.\tPASS\t.\tGT:DP\t"
        + first_record
        + "\n"
        + "1\t200\t.\tG\tT\t.\tPASS\t.\tGT:DP\t"
        + second_record
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.mark.parametrize("sample_order", [
    ("FATHER", "PROBAND", "MOTHER"),
    ("MOTHER", "PROBAND", "FATHER"),
    ("PROBAND", "FATHER", "MOTHER"),
])
@pytest.mark.parametrize("selected_sample", ["PROBAND", "FATHER", "MOTHER"])
def test_normalized_variant_stream_uses_only_exactly_selected_sample(
    tmp_path: Path,
    sample_order: tuple[str, ...],
    selected_sample: str,
):
    path = tmp_path / "family.vcf"
    _write_family_vcf(path, sample_order)

    variants = list(
        iter_normalized_vcf(path, "GRCh38", sample_name=selected_sample)
    )

    expected_position, expected_gt, expected_dosage = EXPECTED[selected_sample]
    assert len(variants) == 1
    variant = variants[0]
    assert variant.position == expected_position
    assert variant.sample_call is not None
    assert variant.sample_call["sample_name"] == selected_sample
    assert variant.sample_call["genotype"] == expected_gt
    assert variant.sample_call["source_genotype"] == expected_gt
    assert variant.sample_call["selected_alt_dosage"] == expected_dosage
    assert variant.sample_call["other_alt_dosage"] == 0


@pytest.mark.parametrize("sample_order", list(permutations(("FATHER", "PROBAND", "MOTHER"))))
def test_unselected_multisample_input_never_falls_back_to_first_sample(
    tmp_path: Path,
    sample_order: tuple[str, ...],
):
    path = tmp_path / "family.vcf"
    _write_family_vcf(path, sample_order)

    with pytest.raises(
        VCFValidationError,
        match="Multisample VCF parsing requires an explicit sample_name",
    ):
        list(iter_normalized_vcf(path, "GRCh38"))


def test_unknown_specimen_sample_mapping_is_rejected_without_fallback(tmp_path: Path):
    path = tmp_path / "family.vcf"
    _write_family_vcf(path, ("FATHER", "PROBAND", "MOTHER"))

    with pytest.raises(
        VCFValidationError,
        match="Selected VCF sample 'SIBLING' is not present",
    ):
        list(iter_normalized_vcf(path, "GRCh38", sample_name="SIBLING"))


def test_worker_partition_snapshot_preserves_the_selected_sample_call(tmp_path: Path):
    from backend.app.workflows.variant import _normalized_partition_metadata

    path = tmp_path / "family.vcf"
    _write_family_vcf(path, ("FATHER", "PROBAND", "MOTHER"))
    selected = list(
        iter_normalized_vcf(path, "GRCh38", sample_name="PROBAND")
    )
    assert len(selected) == 1

    metadata = _normalized_partition_metadata([uuid4()], selected)
    calls = metadata["sample_calls"]

    assert len(calls) == 1
    assert calls[0]["sample_name"] == "PROBAND"
    assert calls[0]["genotype"] == "1/1"
    assert calls[0]["source_genotype"] == "1/1"
    assert calls[0]["selected_alt_dosage"] == 2
    assert calls[0]["other_alt_dosage"] == 0
