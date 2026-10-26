import pytest

from backend.app.domain.acmg import ACMG_CRITERIA, proposed_classification


def test_unversioned_legacy_classifier_fails_closed():
    with pytest.raises(RuntimeError, match="legacy domain classifier is disabled"):
        proposed_classification([{"criterion": "PVS1", "strength": "VERY_STRONG"}])


def test_legacy_criteria_catalog_does_not_advertise_retired_pp5_or_bp6():
    assert "PP5" not in ACMG_CRITERIA["PATHOGENIC"]
    assert "BP6" not in ACMG_CRITERIA["BENIGN"]
