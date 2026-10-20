from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, select


def test_case_access_migration_preserves_active_members_on_existing_cases(tmp_path, monkeypatch):
    db_path = tmp_path / "case-access-migration.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0047_specimen_case_identity")

    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    now = datetime.now(timezone.utc)
    org_id, bioinformatician_id, reviewer_id, read_only_id, suspended_user_id, case_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    users = [
        (bioinformatician_id, "bioinformatician", "active-bioinformatician"),
        (reviewer_id, "reviewer", "active-reviewer"),
        (read_only_id, "read_only", "active-read-only"),
        (suspended_user_id, "reviewer", "suspended-reviewer"),
    ]
    with engine.begin() as connection:
        connection.execute(metadata.tables["organizations"].insert(), {
            "id": org_id.hex, "name": "Migration Lab", "created_at": now, "updated_at": now,
        })
        connection.execute(metadata.tables["users"].insert(), [
            {
                "id": user_id.hex, "organization_id": org_id.hex,
                "external_subject": subject, "email": f"{subject}@example.test",
                "display_name": subject, "role": role, "status": "ACTIVE",
                "created_at": now, "updated_at": now,
            }
            for user_id, role, subject in users
        ])
        connection.execute(metadata.tables["organization_memberships"].insert(), [
            {
                "id": uuid4().hex, "organization_id": org_id.hex, "user_id": user_id.hex,
                "role": role, "status": "SUSPENDED" if user_id == suspended_user_id else "ACTIVE",
                "created_at": now, "updated_at": now,
            }
            for user_id, role, _subject in users
        ])
        connection.execute(metadata.tables["cases"].insert(), {
            "id": case_id.hex, "organization_id": org_id.hex, "case_identifier": "LEGACY-1",
            "status": "DRAFT", "clinical_context": {}, "language": "en",
            "created_by": bioinformatician_id.hex, "created_at": now, "updated_at": now,
        })

    command.upgrade(cfg, "head")
    migrated = MetaData()
    migrated.reflect(engine, only=["case_access_grants"])
    grant_table = migrated.tables["case_access_grants"]
    with engine.connect() as connection:
        grants = connection.execute(select(grant_table)).mappings().all()
    assert len(grants) == 3
    by_user = {UUID(str(row["user_id"])): row for row in grants}
    assert set(by_user) == {bioinformatician_id, reviewer_id, read_only_id}
    assert all(UUID(str(row["case_id"])) == case_id for row in grants)

    assert by_user[bioinformatician_id]["can_read"] is True
    assert by_user[bioinformatician_id]["can_write"] is True
    assert by_user[bioinformatician_id]["can_review"] is False
    assert by_user[reviewer_id]["can_read"] is True
    assert by_user[reviewer_id]["can_write"] is False
    assert by_user[reviewer_id]["can_review"] is True
    assert by_user[read_only_id]["can_read"] is True
    assert by_user[read_only_id]["can_write"] is False
    assert by_user[read_only_id]["can_review"] is False
    engine.dispose()
