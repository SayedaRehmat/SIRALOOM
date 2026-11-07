"""VCFv4.5 base-modification sequence-position oracle.

This module models the source-defined order of per-allele Number=M slots.
It deliberately does not claim to verify the biological meaning of numeric
values supplied in a VCF: those values do not carry per-slot labels.
"""

from __future__ import annotations

from typing import Literal

Strand = Literal["+", "-"]


def base_modification_positions(
    sequence: str,
    modified_base: str,
) -> tuple[tuple[int, Strand], ...]:
    """Return zero-based sequence positions and strand slots in VCF order.

    For a specific modified base, a matching base is a positive-strand slot
    and its complement is a negative-strand slot. Slots are emitted in
    sequence order. For modified base N, both strands are emitted at each
    sequence position, positive then negative, as specified by VCFv4.5.

    The helper accepts concrete A/C/G/T sequences only. Ambiguous sequence
    symbols require a separately adjudicated interpretation and are rejected
    rather than silently assigned a slot.
    """
    sequence = sequence.upper()
    modified_base = modified_base.upper()
    if not sequence or any(base not in "ACGT" for base in sequence):
        raise ValueError("sequence must be a non-empty concrete A/C/G/T sequence")
    if modified_base not in "ACGTUN":
        raise ValueError("modified_base must be one of A, C, G, T, U, or N")

    if modified_base == "N":
        return tuple(
            (position, strand)
            for position in range(len(sequence))
            for strand in ("+", "-")
        )

    base = "T" if modified_base == "U" else modified_base
    complement = {"A": "T", "C": "G", "G": "C", "T": "A"}[base]
    slots: list[tuple[int, Strand]] = []
    for position, observed in enumerate(sequence):
        if observed == base:
            slots.append((position, "+"))
        elif observed == complement:
            slots.append((position, "-"))
    return tuple(slots)

def genotype_base_modification_slots(
    genotype: str,
    reference: str,
    alternates: tuple[str, ...] | list[str],
    modified_base: str,
    *,
    fileformat: str = "VCFv4.5",
) -> tuple[tuple[int, int, Strand], ...]:
    """Return Number=M slots in GT order as (global allele index, offset, strand).

    This is a test oracle for concrete sequence alleles. Missing and symbolic
    alleles contribute no slots. Repeated unphased allele indexes are emitted
    only at their first unphased occurrence; phased copies remain distinct.
    """
    import re

    has_leading_phase = (
        fileformat in {"VCFv4.4", "VCFv4.5"}
        and genotype[:1] in {"/", "|"}
    )
    value = genotype[1:] if has_leading_phase else genotype
    tokens = re.split(r"[/|]", value)
    separators = re.findall(r"[/|]", value)
    if (
        not value
        or any(token == "" for token in tokens)
        or len(separators) != len(tokens) - 1
    ):
        raise ValueError(f"invalid GT structure: {genotype!r}")

    first_separator = genotype[0] if has_leading_phase else (
        "/" if "/" in separators else "|"
    )
    seen_unphased: set[int] = set()
    slots: list[tuple[int, int, Strand]] = []
    for index, token in enumerate(tokens):
        if token == ".":
            continue
        if not token.isdigit():
            raise ValueError(f"invalid GT allele index: {token!r}")
        allele_index = int(token)
        if allele_index > len(alternates):
            raise ValueError(f"GT allele index out of range: {allele_index}")
        preceding_separator = (
            first_separator if index == 0 else separators[index - 1]
        )
        if preceding_separator == "/":
            if allele_index in seen_unphased:
                continue
            seen_unphased.add(allele_index)

        allele = reference if allele_index == 0 else alternates[allele_index - 1]
        allele = allele.upper()
        if not allele or any(base not in "ACGT" for base in allele):
            # Symbolic alleles contribute no sequence slots. Ambiguous
            # sequence alleles are not silently treated as symbolic.
            if allele.startswith("<") and allele.endswith(">"):
                continue
            raise ValueError(f"non-concrete sequence allele: {allele!r}")
        slots.extend(
            (allele_index, position, strand)
            for position, strand in base_modification_positions(
                allele, modified_base
            )
        )
    return tuple(slots)

