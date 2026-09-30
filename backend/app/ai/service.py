from __future__ import annotations

from backend.app.ai.contracts import AISummary, InterpretationContext


class AIServiceError(RuntimeError):
    pass


class InterpretationAI:
    """Decision-support interface; implementations must not classify variants."""

    def summarize(self, context: InterpretationContext) -> AISummary:
        raise NotImplementedError
