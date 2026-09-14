from __future__ import annotations
from typing import Any
import httpx
import time
from backend.app.config import settings
from backend.app.domain.schemas import CanonicalVariant

class GeneBeError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class GeneBeProvider:
    provider_id = "genebe"
    provider_version = "api-public-v1"

    def capabilities(self) -> set[str]:
        return {"ANNOTATION", "ACMG_CRITERIA_SUPPORT"}

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def annotate(self, variants: list[CanonicalVariant], context: dict[str, Any]) -> list[dict]:
        if not settings.genebe_enabled:
            raise GeneBeError("GeneBe provider is disabled")
        if not settings.genebe_email or not settings.genebe_api_key:
            raise GeneBeError("GeneBe credentials are not configured")
        if not variants:
            return []
        if len(variants) > settings.genebe_max_batch:
            raise GeneBeError(f"Batch exceeds configured limit {settings.genebe_max_batch}")
        genome = context.get("genome", "hg38")
        payload = [
            {"chr": v.chromosome.removeprefix("chr"), "pos": v.position, "ref": v.reference, "alt": v.alternate}
            for v in variants
        ]
        url = f"{settings.genebe_base_url.rstrip('/')}/variants"
        last_error: GeneBeError | None = None
        attempts = max(1, settings.genebe_retry_attempts)
        for attempt in range(1, attempts + 1):
            response = None
            try:
                with httpx.Client(timeout=settings.genebe_timeout_seconds) as client:
                    response = client.post(
                        url,
                        params={"genome": genome},
                        headers=self._headers(),
                        json=payload,
                        auth=(settings.genebe_email, settings.genebe_api_key),
                    )
                    response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status == 408 or status == 429 or 500 <= status <= 599
                last_error = GeneBeError(
                    f"GeneBe HTTP {status}: {exc.response.text[:500]}",
                    retryable=retryable,
                )
            except httpx.HTTPError as exc:
                last_error = GeneBeError(f"GeneBe request failed: {exc}", retryable=True)
            if not last_error or not last_error.retryable or attempt >= attempts:
                raise last_error
            retry_after = None
            try:
                retry_after = float(response.headers.get("Retry-After")) if response is not None else None
            except (TypeError, ValueError):
                retry_after = None
            delay = retry_after if retry_after is not None else min(
                settings.genebe_retry_max_backoff_seconds,
                settings.genebe_retry_backoff_seconds * (2 ** (attempt - 1)),
            )
            time.sleep(max(0.0, delay))
        else:
            raise last_error or GeneBeError("GeneBe request failed")
        if isinstance(data, dict) and isinstance(data.get("variants"), list):
            return data["variants"]
        if isinstance(data, list):
            return data
        raise GeneBeError("Unexpected GeneBe response: expected object with variants[]")
