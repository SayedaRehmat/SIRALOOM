from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain import resource_discovery
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource


class FakeEntryPoint:
    def load(self):
        return FakeProvider


class FakeEntryPoints:
    def select(self, *, group):
        assert group == "siraloom.resource_providers"
        return [FakeEntryPoint()]


class FakeProvider:
    def discover(self):
        return [{
            "name": "FutureDB",
            "provider": "FutureProvider",
            "resource_type": "EVIDENCE",
            "version": "2026.10",
            "genome_build": "GRCh38",
            "access_method": "OBJECT_STORAGE",
            "checksum": "a" * 64,
            "location": "blob://future/2026.10",
            "metadata": {"release_channel": "stable"},
        }]


def test_provider_discovery_registers_candidates_without_activation(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Resource.__table__])
    monkeypatch.setattr(resource_discovery, "entry_points", lambda: FakeEntryPoints())

    with Session(engine) as db:
        result = resource_discovery.discover_resource_candidates(db)
        assert result == {"candidates_discovered": 1, "providers_failed": 0}
        resource = db.query(Resource).one()
        assert resource.status == "CANDIDATE"
        assert resource.metadata_json["release_channel"] == "stable"
        assert resource.metadata_json["discovery_provider"].endswith(".FakeProvider")
