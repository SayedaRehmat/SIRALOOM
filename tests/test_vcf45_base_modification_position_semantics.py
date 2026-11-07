from __future__ import annotations

import pytest

from backend.app.domain.vcf45_base_modification import base_modification_positions


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
        ("TCC", "U", ((0, "-"),)),
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
