import httpx
import pytest

from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
from backend.app.config import settings
from backend.app.domain.schemas import CanonicalVariant


class FakeClient:
    responses = []
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        type(self).calls += 1
        return type(self).responses.pop(0)


def variant():
    return CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=100, reference="A", alternate="G"
    )


def test_genebe_retries_transient_http_error(monkeypatch):
    settings.genebe_enabled = True
    settings.genebe_email = "test@example.org"
    settings.genebe_api_key = "secret"
    settings.genebe_retry_attempts = 3
    settings.genebe_retry_backoff_seconds = 0
    settings.genebe_retry_max_backoff_seconds = 0
    FakeClient.calls = 0
    FakeClient.responses = [
        httpx.Response(503, text="temporary", request=httpx.Request("POST", "https://example.test")),
        httpx.Response(200, json={"variants": [{"chr": "1", "pos": 100, "ref": "A", "alt": "G"}]}, request=httpx.Request("POST", "https://example.test")),
    ]
    monkeypatch.setattr("backend.app.adapters.annotation.genebe.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.app.adapters.annotation.genebe.time.sleep", lambda _seconds: None)

    result = GeneBeProvider().annotate([variant()], {"genome": "hg38"})
    assert FakeClient.calls == 2
    assert result[0]["pos"] == 100


def test_genebe_does_not_retry_non_transient_http_error(monkeypatch):
    settings.genebe_enabled = True
    settings.genebe_email = "test@example.org"
    settings.genebe_api_key = "secret"
    settings.genebe_retry_attempts = 3
    FakeClient.calls = 0
    FakeClient.responses = [
        httpx.Response(401, text="unauthorized", request=httpx.Request("POST", "https://example.test")),
    ]
    monkeypatch.setattr("backend.app.adapters.annotation.genebe.httpx.Client", FakeClient)

    with pytest.raises(GeneBeError) as exc:
        GeneBeProvider().annotate([variant()], {"genome": "hg38"})
    assert exc.value.retryable is False
    assert FakeClient.calls == 1
