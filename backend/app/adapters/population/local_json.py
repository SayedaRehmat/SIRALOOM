from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID

class LocalJSONPopulationProvider:
    provider_id = "local-json"
    def __init__(self, path: str):
        self.path = Path(path)

    def query(self, variant_ids: list[UUID], population_codes: list[str], context: dict) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        wanted = {str(v) for v in variant_ids}
        return [row for row in data if str(row.get("variant_id")) in wanted and row.get("population_code") in population_codes]
