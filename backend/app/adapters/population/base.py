from typing import Protocol
from uuid import UUID

class PopulationProvider(Protocol):
    provider_id: str
    def query(self, variant_ids: list[UUID], population_codes: list[str], context: dict) -> list[dict]: ...
