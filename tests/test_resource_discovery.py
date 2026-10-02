from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain import resource_discovery
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, Resource, ResourceDiscovery, ResourceStaging


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
            "source_contract": {
                "publisher": "FutureProvider",
                "canonical_source_url": "https://example.org/resource",
                "artifact_url": "https://example.org/resource/2026.10",
                "release_identity": "2026.10",
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://example.org/resource/docs",
            },
        }]


def test_provider_discovery_registers_candidates_without_activation(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Organization.__table__, Resource.__table__, ResourceDiscovery.__table__, ResourceStaging.__table__])
    monkeypatch.setattr(resource_discovery, "entry_points", lambda: FakeEntryPoints())

    with Session(engine) as db:
        result = resource_discovery.discover_resource_candidates(db)
        assert result == {"candidates_discovered": 1, "providers_failed": 0}
        resource = db.query(Resource).one()
        assert resource.status == "CANDIDATE"
        assert resource.metadata_json["release_channel"] == "stable"
        assert resource.metadata_json["discovery_provider"].endswith(".FakeProvider")


def test_provider_discovery_persists_source_identity_and_never_activates(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Organization.__table__, Resource.__table__, ResourceDiscovery.__table__, ResourceStaging.__table__])
    monkeypatch.setattr(resource_discovery, "entry_points", lambda: FakeEntryPoints())

    with Session(engine) as db:
        resource_discovery.discover_resource_candidates(db)
        discovery = db.query(ResourceDiscovery).one()
        assert discovery.publisher == "FutureProvider"
        assert discovery.release_identity == "2026.10"
        assert discovery.status == "DISCOVERED"
        assert discovery.authority_evidence_url == "https://example.org/resource/docs"
        assert db.query(ResourceStaging).count() == 0
        assert db.query(Resource).one().status == "CANDIDATE"
