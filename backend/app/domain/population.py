from __future__ import annotations

from math import isfinite
from typing import Any


def qualified_allele_frequency(allele_frequency: Any, allele_number: Any) -> float | None:
    """Expose AF only when its denominator is positive and AF is finite and in range."""
    try:
        an = int(allele_number)
        af = float(allele_frequency)
    except (TypeError, ValueError, OverflowError):
        return None
    if an <= 0 or not isfinite(af) or af < 0 or af > 1:
        return None
    return af
