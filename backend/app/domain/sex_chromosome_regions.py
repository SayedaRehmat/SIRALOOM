"""Build-specific human pseudoautosomal-region (PAR) classification.

Coordinates are 1-based and closed, matching VCF POS and GRC PAR tables.
This module classifies reference intervals only; it never infers sample
karyotype or enforces genotype ploidy from chromosome labels.
"""
from __future__ import annotations

import re

# Genome Reference Consortium coordinates, 1-based inclusive. Patch releases
# retain the chromosome coordinate system of their major assembly.
_HUMAN_PAR_INTERVALS = {
    "GRCh37": {
        "X": ((60_001, 2_699_520), (154_931_044, 155_260_560)),
        "Y": ((10_001, 2_649_520), (59_034_050, 59_363_566)),
    },
    "GRCh38": {
        "X": ((10_001, 2_781_479), (155_701_383, 156_030_895)),
        "Y": ((10_001, 2_781_479), (56_887_903, 57_217_415)),
    },
}
_BUILD_RE = re.compile(r"^GRCH(37|38)(?:\.P[0-9]+)?$", re.IGNORECASE)
_CONTIG_ALIASES = {"X": "X", "CHRX": "X", "Y": "Y", "CHRY": "Y"}


def normalize_human_reference_build(reference_build: str) -> str:
    """Normalize supported human assembly names to GRCh37 or GRCh38."""
    if not isinstance(reference_build, str) or not reference_build.strip():
        raise ValueError("A non-empty human reference build is required")
    value = reference_build.strip()
    aliases = {"HG19": "GRCh37", "HG38": "GRCh38"}
    if value.upper() in aliases:
        return aliases[value.upper()]
    match = _BUILD_RE.fullmatch(value.upper())
    if match is None:
        raise ValueError(f"Unsupported human reference build: {reference_build!r}")
    return "GRCh37" if match.group(1) == "37" else "GRCh38"


def classify_sex_chromosome_interval(
    contig: str,
    start: int,
    end: int,
    reference_build: str,
) -> str:
    """Classify a 1-based closed interval as PAR, non-PAR, or boundary-crossing."""
    build = normalize_human_reference_build(reference_build)
    if not isinstance(contig, str) or not contig.strip():
        raise ValueError("A non-empty contig name is required")
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, int) or not isinstance(end, int)
    ):
        raise ValueError("Genomic interval coordinates must be integers")
    if start < 1 or end < start:
        raise ValueError("Genomic interval must be 1-based, non-empty, and closed")
    chromosome = _CONTIG_ALIASES.get(contig.upper())
    if chromosome is None:
        return "NOT_SEX_CHROMOSOME"
    intervals = _HUMAN_PAR_INTERVALS[build][chromosome]
    overlaps = [
        (par_start, par_end)
        for par_start, par_end in intervals
        if start <= par_end and end >= par_start
    ]
    if not overlaps:
        return "NON_PAR"
    if any(start >= par_start and end <= par_end for par_start, par_end in overlaps):
        return "PAR"
    return "PAR_BOUNDARY_CROSSING"
