from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from uuid import uuid4

from backend.app.domain import resource_discovery
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Notification, Organization, OrganizationMembership, Resource, ResourceDiscovery,
    ResourceStaging, User,
)


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
    Base.metadata.create_all(engine, tables=[Organization.__table__, User.__table__, OrganizationMembership.__table__, Notification.__table__, Resource.__table__, ResourceDiscovery.__table__, ResourceStaging.__table__])
    monkeypatch.setattr(resource_discovery, "entry_points", lambda: FakeEntryPoints())

    with Session(engine) as db:
        organization_id = uuid4()
        user_id = uuid4()
        db.add(Organization(id=organization_id, name="Discovery Lab", external_identifier="discovery-lab"))
        db.add(User(id=user_id, organization_id=organization_id, external_subject="discovery-user", email="lab@example.test", display_name="Lab Director", role="lab_director", status="ACTIVE"))
        db.add(OrganizationMembership(id=uuid4(), organization_id=organization_id, user_id=user_id, role="lab_director", status="ACTIVE"))
        db.commit()

        result = resource_discovery.discover_resource_candidates(db)
        assert result == {"candidates_discovered": 1, "providers_failed": 0}
        resource = db.query(Resource).one()
        discovery = db.query(ResourceDiscovery).one()
        assert resource.status == "CANDIDATE"
        assert resource.metadata_json["release_channel"] == "stable"
        assert resource.metadata_json["discovery_provider"].endswith(".FakeProvider")
        notifications = db.query(Notification).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "RESOURCE_RELEASE_DISCOVERED"
        assert notifications[0].organization_id == organization_id
        assert notifications[0].metadata_json["discovery_id"] == str(discovery.id)

        # A repeat scan must not send the same release notification again.
        resource_discovery.discover_resource_candidates(db)
        assert db.query(Notification).count() == 1


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


def test_scientific_resource_discovery_is_scheduled_daily():
    from backend.app.infrastructure.queue.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["discover-scientific-resource-releases-daily"]["task"] == "siraloom.discover_scientific_resources"
    assert schedule["discover-scientific-resource-releases-daily"]["schedule"] == 86400.0


def test_production_compose_runs_one_persistent_beat_scheduler():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert compose.count("  beat:" + chr(10)) == 1
    beat_block = compose.split("  beat:" + chr(10), 1)[1].split(chr(10) + "  frontend:", 1)[0]
    assert "celery" in beat_block
    assert "beat" in beat_block
    assert "${SIRALOOM_BEAT_HOST_PATH:-beat_data}:/data/siraloom/beat" in beat_block
