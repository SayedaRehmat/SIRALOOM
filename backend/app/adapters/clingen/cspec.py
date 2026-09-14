"""Read-only ClinGen Criteria Specification Registry (CSpec) client.

The CSpec service is currently documented as a public REST API returning JSON.
SIRALOOM treats the service as an external knowledge source, never as the
system of record. Responses are normalized into a provider-neutral snapshot
and the raw response can be retained by the caller for provenance.

This adapter deliberately uses only documented identity/list endpoints. It
never guesses undocumented search routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class CSpecEntity:
    ent_id: str
    ent_type: str
    ldh_id: str | None
    ent_iri: str | None
    content: dict[str, Any]
    modified: str | None
    raw: dict[str, Any]


class CSpecClientError(RuntimeError):
    pass


class CSpecClient:
    def __init__(
        self,
        *,
        base_url: str = "https://cspec.clinicalgenome.org/cspec",
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self.timeout_seconds)

    def service_metadata(self) -> dict[str, Any]:
        return self._get("/srvc")

    def get_entity(self, entity_type: str, entity_id: str, *, detail: str = "high") -> CSpecEntity:
        self._validate_type(entity_type)
        if detail not in {"low", "med", "high"}:
            raise ValueError("detail must be low, med, or high")
        payload = self._get(f"/{entity_type}/id/{entity_id}", params={"detail": detail})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise CSpecClientError("CSpec response does not contain a data object")
        return self._parse_entity(data, fallback_type=entity_type, fallback_id=entity_id)

    def list_entities(
        self,
        entity_type: str,
        *,
        ids: list[str] | None = None,
        page: int = 1,
        page_size: int = 250,
        detail: str = "low",
    ) -> list[CSpecEntity]:
        self._validate_type(entity_type)
        if page < 1 or not 1 <= page_size <= 250:
            raise ValueError("page must be >= 1 and page_size must be between 1 and 250")
        if detail not in {"low", "med", "high"}:
            raise ValueError("detail must be low, med, or high")
        params: dict[str, Any] = {"pg": page, "pgSize": page_size, "detail": detail}
        if ids:
            params["ids"] = ",".join(ids)
        payload = self._get(f"/{entity_type}/id", params=params)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            # CSpec's list response is expected to expose data as a list. Fail
            # closed rather than interpreting an unknown representation.
            raise CSpecClientError("CSpec list response does not contain a data list")
        return [self._parse_entity(item, fallback_type=entity_type) for item in data if isinstance(item, dict)]

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client = self._get_client()
        should_close = self._client is None
        try:
            response = client.get(self.base_url + path, params=params)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise CSpecClientError("CSpec response is not a JSON object")
            return body
        except (httpx.HTTPError, ValueError) as exc:
            raise CSpecClientError(f"CSpec request failed: {exc}") from exc
        finally:
            if should_close:
                client.close()

    @staticmethod
    def _validate_type(entity_type: str) -> None:
        allowed = {
            "RuleSet",
            "SequenceVariantInterpretation",
            "CriteriaCode",
            "Gene",
            "Disease",
            "Organization",
            "Assertion",
            "EvidenceCategory",
        }
        if entity_type not in allowed:
            raise ValueError(f"Unsupported CSpec entity type: {entity_type}")

    @staticmethod
    def _parse_entity(data: dict[str, Any], *, fallback_type: str, fallback_id: str | None = None) -> CSpecEntity:
        ent_id = str(data.get("entId") or fallback_id or "")
        ent_type = str(data.get("entType") or fallback_type)
        if not ent_id:
            raise CSpecClientError("CSpec entity is missing entId")
        content = data.get("entContent")
        if not isinstance(content, dict):
            content = {}
        return CSpecEntity(
            ent_id=ent_id,
            ent_type=ent_type,
            ldh_id=str(data["ldhId"]) if data.get("ldhId") is not None else None,
            ent_iri=str(data["entIri"]) if data.get("entIri") is not None else None,
            content=content,
            modified=str(data["modified"]) if data.get("modified") is not None else None,
            raw=data,
        )
