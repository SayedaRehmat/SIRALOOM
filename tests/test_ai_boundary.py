import json

import httpx
import pytest

from backend.app.ai.azure_openai import AzureOpenAIInterpretationAI
from backend.app.ai.contracts import EvidenceItem, InterpretationContext
from backend.app.ai.service import AIServiceError


def _context() -> InterpretationContext:
    return InterpretationContext(
        variant_id="variant-1",
        genome_build="GRCh38",
        gene="TEST1",
        disease="TEST-DISEASE",
        evidence=(
            EvidenceItem(
                evidence_id="ev-1",
                evidence_type="CLINICAL_DATABASE",
                statement="A curated database assertion is available.",
                source_name="ClinVar",
                source_version="2026-01",
                payload={"review_status": "reviewed"},
            ),
        ),
    )


def test_ai_requires_persisted_evidence():
    ai = AzureOpenAIInterpretationAI(
        endpoint="https://example.invalid",
        api_key="test",
        deployment="test",
        api_version="2026-01-01",
        model_version="test-model",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))),
    )
    empty = InterpretationContext(
        variant_id="v", genome_build="GRCh38", gene=None, disease=None, evidence=(),
    )
    with pytest.raises(AIServiceError, match="persisted evidence"):
        ai.summarize(empty)


def test_ai_rejects_untraceable_evidence_id():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({
                                "summary": "Summary",
                                "evidence_ids": ["not-supplied"],
                                "uncertainties": [],
                                "review_questions": [],
                            }),
                        }
                    ]
                }
            ]
        }
        return httpx.Response(200, json=body)

    ai = AzureOpenAIInterpretationAI(
        endpoint="https://example.invalid",
        api_key="test",
        deployment="test",
        api_version="2026-01-01",
        model_version="test-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIServiceError, match="evidence ID"):
        ai.summarize(_context())


def test_ai_returns_only_structured_evidence_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        assert b"Do not assign or recommend ACMG/AMP criteria" in payload
        body = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({
                                "summary": "The supplied curated assertion is available.",
                                "evidence_ids": ["ev-1"],
                                "uncertainties": ["The assertion still requires human review."],
                                "review_questions": ["Confirm applicability to the case disease."],
                            }),
                        }
                    ]
                }
            ]
        }
        return httpx.Response(200, json=body)

    ai = AzureOpenAIInterpretationAI(
        endpoint="https://example.invalid",
        api_key="test",
        deployment="test",
        api_version="2026-01-01",
        model_version="test-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = ai.summarize(_context())
    assert result.evidence_ids == ("ev-1",)
    assert result.model_provider == "azure-openai"
    assert result.prompt_version == "1.0"
