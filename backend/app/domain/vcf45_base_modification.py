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
