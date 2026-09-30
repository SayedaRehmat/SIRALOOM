from __future__ import annotations

import json
from typing import Any

import httpx

from backend.app.ai.contracts import AISummary, InterpretationContext
from backend.app.ai.service import AIServiceError, InterpretationAI


class AzureOpenAIInterpretationAI(InterpretationAI):
    """Azure OpenAI adapter for evidence-grounded decision support.

    Deliberately not connected to the ACMG engine or sign-out workflow.
    """

    provider_id = "azure-openai"
    prompt_version = "1.0"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        model_version: str,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.model_version = model_version
        self.timeout_seconds = timeout_seconds
        self._client = client

    def summarize(self, context: InterpretationContext) -> AISummary:
        if not context.evidence:
            raise AIServiceError("AI synthesis requires at least one persisted evidence item.")

        body: dict[str, Any] = {
            "model": self.deployment,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are SIRALOOM's evidence synthesis assistant. "
                        "Summarize only supplied evidence. Never invent facts. "
                        "Do not assign or recommend ACMG/AMP criteria, pathogenicity "
                        "classifications, ClinGen criteria, or report sign-out. "
                        "Every factual statement must be traceable to supplied "
                        "evidence_id values. Identify uncertainty and human-review questions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "variant_id": context.variant_id,
                            "genome_build": context.genome_build,
                            "gene": context.gene,
                            "disease": context.disease,
                            "phenotype_terms": list(context.phenotype_terms),
                            "existing_classification": context.existing_classification,
                            "evidence": [
                                {
                                    "evidence_id": item.evidence_id,
                                    "type": item.evidence_type,
                                    "statement": item.statement,
                                    "source": item.source_name,
                                    "source_version": item.source_version,
                                    "payload": item.payload,
                                }
                                for item in context.evidence
                            ],
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "siraloom_evidence_summary",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "uncertainties": {"type": "array", "items": {"type": "string"}},
                            "review_questions": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["summary", "evidence_ids", "uncertainties", "review_questions"],
                        "additionalProperties": False,
                    },
                }
            },
        }

        close_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                f"{self.endpoint}/openai/v1/responses?api-version={self.api_version}",
                headers={"api-key": self.api_key, "content-type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIServiceError(f"Azure OpenAI request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()

        parsed = payload.get("output_parsed")
        if parsed is None:
            for item in payload.get("output", []):
                for content in item.get("content", []):
                    raw = content.get("text") or content.get("json")
                    if content.get("type") in {"output_text", "json"} and raw is not None:
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                        break
                if parsed is not None:
                    break

        if not isinstance(parsed, dict):
            raise AIServiceError("Azure OpenAI returned no structured evidence summary.")

        supplied_ids = {item.evidence_id for item in context.evidence}
        cited_ids = tuple(str(x) for x in parsed.get("evidence_ids", []))
        if any(x not in supplied_ids for x in cited_ids):
            raise AIServiceError("AI returned an evidence ID that was not supplied to the model.")

        return AISummary(
            summary=str(parsed.get("summary") or ""),
            evidence_ids=cited_ids,
            uncertainties=tuple(str(x) for x in parsed.get("uncertainties", [])),
            review_questions=tuple(str(x) for x in parsed.get("review_questions", [])),
            model_provider=self.provider_id,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )
