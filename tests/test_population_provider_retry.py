"""Retry classification for gnomAD API failures; no live provider calls."""
from types import SimpleNamespace

import httpx
import pytest

from backend.app.adapters.population.gnomad import GnomADGraphQLProvider, GnomADProviderError


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://provider.invalid/graphql")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _Client:
    def __init__(self, *, status_code=None, exception=None, **_kwargs):
        self.status_code = status_code
        self.exception = exception

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        if self.exception is not None:
            raise self.exception
        return _Response(self.status_code)


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(429, True), (500, True), (503, True), (400, False), (401, False)],
)
def test_gnomad_http_status_has_explicit_retry_classification(
    monkeypatch, status_code, retryable
):
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _Client(status_code=status_code, **kwargs),
    )
    provider = GnomADGraphQLProvider(endpoint="https://provider.invalid/graphql")
    variant = SimpleNamespace(
        chromosome="1", position=123, reference="A", alternate="G"
    )

    with pytest.raises(GnomADProviderError) as caught:
        provider.query_variant(variant)

    assert caught.value.retryable is retryable


def test_gnomad_timeout_is_retryable(monkeypatch):
    request = httpx.Request("POST", "https://provider.invalid/graphql")
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kwargs: _Client(
            exception=httpx.ReadTimeout("injected timeout", request=request),
            **kwargs,
        ),
    )
    provider = GnomADGraphQLProvider(endpoint="https://provider.invalid/graphql")
    variant = SimpleNamespace(
        chromosome="1", position=123, reference="A", alternate="G"
    )

    with pytest.raises(GnomADProviderError) as caught:
        provider.query_variant(variant)

    assert caught.value.retryable is True
