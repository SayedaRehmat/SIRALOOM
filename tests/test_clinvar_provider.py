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
    assert candidate["provider"] == "CLINVAR"
    assert candidate["resource_type"] == "CLINICAL_DATABASE"
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


def test_clinvar_stage_streams_exact_official_url(monkeypatch, tmp_path):
    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size):
            assert chunk_size == 1024 * 1024
            yield b"clinvar-release-"
            yield b"bytes"

    monkeypatch.setattr(
        "backend.app.infrastructure.resource_providers.clinvar.httpx.stream",
        lambda method, url, **kwargs: FakeStreamResponse(),
    )

    destination = tmp_path / "ClinVarVCVRelease_2026-09.xml.gz"
    descriptor = {
        "location": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/ClinVarVCVRelease_2026-09.xml.gz",
        "version": "2026-09",
    }

    result = ClinVarReleaseProvider().stage(descriptor, destination)

    assert destination.read_bytes() == b"clinvar-release-bytes"
    assert result.size_bytes == len(b"clinvar-release-bytes")
    assert result.sha256 == "5a08150b23f8ed27cb106d2863cef271dd02ff327caf00f1b908d8bf313c5108"
    assert result.metadata["integrity"] == "TRANSPORT_DIGEST_ONLY"
    assert result.metadata["source_checksum_verified"] is False


def test_clinvar_stage_rejects_non_ncbi_location(tmp_path):
    descriptor = {
        "location": "https://example.invalid/ClinVarVCVRelease_2026-09.xml.gz",
        "version": "2026-09",
    }

    try:
        ClinVarReleaseProvider().stage(
            descriptor, tmp_path / "release.xml.gz"
        )
    except ValueError as exc:
        assert "official NCBI ClinVar URL" in str(exc)
    else:
        raise AssertionError("ClinVar staging must reject non-NCBI locations")
