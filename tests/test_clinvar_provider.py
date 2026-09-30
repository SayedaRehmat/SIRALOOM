from backend.app.infrastructure.resource_providers.clinvar import ClinVarReleaseProvider


class FakeResponse:
    text = """
    <a href="ClinVarVCVRelease_2026-08.xml.gz">ClinVarVCVRelease_2026-08.xml.gz</a>
    <a href="ClinVarVCVRelease_2026-09.xml.gz">ClinVarVCVRelease_2026-09.xml.gz</a>
    <a href="ClinVarVCVRelease_00-latest.xml.gz">ClinVarVCVRelease_00-latest.xml.gz</a>
    """

    def raise_for_status(self):
        return None


def test_clinvar_provider_uses_archived_monthly_release(monkeypatch):
    monkeypatch.setattr(
        "backend.app.infrastructure.resource_providers.clinvar.httpx.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = ClinVarReleaseProvider().discover()

    assert len(result) == 1
    candidate = result[0]
    assert candidate["version"] == "2026-09"
    assert candidate["metadata"]["release_channel"] == "MONTHLY_ARCHIVED"
    assert candidate["metadata"]["release_month"] == "2026-09"
    assert candidate["location"].endswith("ClinVarVCVRelease_2026-09.xml.gz")
    assert candidate["checksum"] is None
    assert candidate["metadata"]["requires_checksum_qualification"] is True


def test_clinvar_provider_rejects_index_without_archived_release(monkeypatch):
    class EmptyResponse:
        text = '<a href="ClinVarVCVRelease_00-latest.xml.gz">latest</a>'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "backend.app.infrastructure.resource_providers.clinvar.httpx.get",
        lambda *args, **kwargs: EmptyResponse(),
    )

    try:
        ClinVarReleaseProvider().discover()
    except RuntimeError as exc:
        assert "no VCV release files" in str(exc)
    else:
        raise AssertionError("latest synchronization feed must not be treated as archived")
