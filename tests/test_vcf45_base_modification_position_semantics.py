from __future__ import annotations

import pytest

from backend.app.domain.vcf45_base_modification import (
    base_modification_positions,
    genotype_base_modification_slots,
)


@pytest.mark.parametrize(
    ("sequence", "modified_base", "expected"),
    [
        # The normative VCFv4.5 example: forward C, then reverse-complement G.
        ("CGA", "C", ((0, "+"), (1, "-"))),
        # The vector follows sequence occurrence order, not strand grouping.
        ("GCA", "C", ((0, "-"), (1, "+"))),
        ("ACGT", "A", ((0, "+"), (3, "-"))),
        ("ACGT", "T", ((0, "-"), (3, "+"))),
        # U is explicitly synonymous with T.
        ("TCC", "U", ((0, "+"),)),
    ],
)
def test_number_m_specific_base_slots_follow_sequence_order_and_strand(
    sequence: str, modified_base: str, expected: tuple[tuple[int, str], ...]
):
    assert base_modification_positions(sequence, modified_base) == expected


def test_number_m_N_emits_positive_then_negative_slot_for_each_base():
    assert base_modification_positions("AC", "N") == (
        (0, "+"),
        (0, "-"),
        (1, "+"),
        (1, "-"),
    )


@pytest.mark.parametrize("sequence", ["", "ACN", "ACR", "AC-"])
def test_number_m_position_oracle_rejects_ambiguous_or_non_sequence_symbols(
    sequence: str,
):
    with pytest.raises(ValueError, match="concrete A/C/G/T"):
        base_modification_positions(sequence, "C")

def test_number_m_values_follow_the_ordered_biological_slots():
    positions = base_modification_positions("CGA", "C")
    values = (0.25, 0.75)
    assert tuple(zip(positions, values)) == (
        ((0, "+"), 0.25),
        ((1, "-"), 0.75),
    )


def test_number_m_slots_follow_gt_allele_order_then_sequence_and_strand_order():
    assert genotype_base_modification_slots(
        "0/1", "CGA", ("TCC",), "C"
    ) == (
        (0, 0, "+"),
        (0, 1, "-"),
        (1, 1, "+"),
        (1, 2, "+"),
    )


def test_number_m_unphased_duplicate_alleles_are_emitted_once():
    assert genotype_base_modification_slots(
        "0/0", "CGA", (), "C"
    ) == ((0, 0, "+"), (0, 1, "-"))


def test_number_m_phased_duplicate_alleles_keep_distinct_slots():
    assert genotype_base_modification_slots(
        "0|0", "CGA", (), "C"
    ) == (
        (0, 0, "+"),
        (0, 1, "-"),
        (0, 0, "+"),
        (0, 1, "-"),
    )


def test_number_m_missing_and_symbolic_gt_alleles_add_no_slots():
    expected_reference_slots = ((0, 0, "+"), (0, 1, "-"))
    assert genotype_base_modification_slots(
        "./0", "CGA", (), "C"
    ) == expected_reference_slots
    assert genotype_base_modification_slots(
        "0/1", "CGA", ("<*>",), "C"
    ) == expected_reference_slots


def test_number_m_N_slots_preserve_positive_then_negative_within_gt_order():
    assert genotype_base_modification_slots(
        "0", "AC", (), "N"
    ) == (
        (0, 0, "+"),
        (0, 0, "-"),
        (0, 1, "+"),
        (0, 1, "-"),
    )

