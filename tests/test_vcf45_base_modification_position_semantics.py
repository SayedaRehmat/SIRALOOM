from __future__ import annotations

import pytest

from backend.app.domain.vcf_validation import (
    _base_modification_allele_slots,
    _expected_base_modification_slots,
)


@pytest.mark.parametrize(
    ("sequence", "modified_base", "expected"),
    [
        ("CGA", "C", [(0, "+", "C"), (1, "-", "G")]),
        ("GCA", "C", [(0, "-", "G"), (1, "+", "C")]),
        ("ACGT", "A", [(0, "+", "A"), (3, "-", "T")]),
        ("ACGT", "T", [(0, "-", "A"), (3, "+", "T")]),
        ("TCC", "U", [(0, "+", "T")]),
    ],
)
def test_production_number_m_slots_follow_sequence_order_and_strand(
    sequence: str, modified_base: str, expected: list[tuple[int, str, str]]
):
    assert _base_modification_allele_slots(sequence, modified_base) == expected


def test_production_number_m_N_emits_positive_then_negative_for_each_base():
    assert _base_modification_allele_slots("AC", "N") == [
        (0, "+", "A"),
        (0, "-", "A"),
        (1, "+", "C"),
        (1, "-", "C"),
    ]


def test_ambiguous_sequence_base_is_not_assigned_to_specific_modification():
    assert _base_modification_allele_slots("CNA", "C") == [(0, "+", "C")]


def test_production_number_m_values_are_mapped_in_gt_allele_order():
    assert _expected_base_modification_slots(
        "0/1", "CGA", ["TCC"], "M5mC", "VCFv4.5", 10
    ) == [
        (0, 0, "+", "C"),
        (0, 1, "-", "G"),
        (1, 1, "+", "C"),
        (1, 2, "+", "C"),
    ]


def test_production_number_m_unphased_duplicate_alleles_are_aggregated():
    assert _expected_base_modification_slots(
        "0/0", "CGA", [], "M5mC", "VCFv4.5", 10
    ) == [(0, 0, "+", "C"), (0, 1, "-", "G")]


def test_production_number_m_phased_duplicate_alleles_keep_distinct_slots():
    assert _expected_base_modification_slots(
        "0|0", "CGA", [], "M5mC", "VCFv4.5", 10
    ) == [
        (0, 0, "+", "C"),
        (0, 1, "-", "G"),
        (0, 0, "+", "C"),
        (0, 1, "-", "G"),
    ]


def test_production_number_m_missing_and_symbolic_alleles_add_no_slots():
    assert _expected_base_modification_slots(
        "./0", "CGA", [], "M5mC", "VCFv4.5", 10
    ) == [(0, 0, "+", "C"), (0, 1, "-", "G")]
    assert _expected_base_modification_slots(
        "0/1", "CGA", ["<*>"], "M5mC", "VCFv4.5", 10
    ) == [(0, 0, "+", "C"), (0, 1, "-", "G")]
