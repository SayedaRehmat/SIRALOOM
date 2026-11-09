from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain import resource_qualification
from backend.app.domain.hgnc_crosswalk import HGNC_ARCHIVE_RELEASE
from backend.app.domain.hgnc_resource_registration import register_and_qualify_hgnc_release
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceQualification, ResourceStaging


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _acquisition_fixture(path: Path) -> None:
    path.mkdir()
    complete = path / "hgnc_complete_set.txt"
    withdrawn = path / "withdrawn.txt"
    complete.write_bytes(b"hgnc complete fixture bytes")
    withdrawn.write_bytes(b"hgnc withdrawn fixture bytes")
    manifest = {
        "schema": "siraloom.hgnc-acquisition.v1",
        "publisher": "HUGO Gene Nomenclature Committee",
        "release": HGNC_ARCHIVE_RELEASE,
        "license": "CC0-1.0",
        "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
        "files": [
            {
                "filename": "hgnc_complete_set.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/hgnc_complete_set_2026-10-06.txt",
                "sha256": _sha(complete),
                "size_bytes": complete.stat().st_size,
            },
            {
                "filename": "withdrawn.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/withdrawn_2026-10-06.txt",
                "sha256": _sha(withdrawn),
                "size_bytes": withdrawn.stat().st_size,
            },
        ],
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_hgnc_release_registers_stages_and_persists_qualification(tmp_path, monkeypatch):
    acquisition = tmp_path / "acquisition"
    managed = tmp_path / "managed" / "hgnc-2026-10-06"
    _acquisition_fixture(acquisition)

    class FakeResolver:
        _approved = {f"HGNC:{index}": {} for index in range(10001)}
        _approved_symbols = {"A": {"HGNC:1"}}
        _alias_index = {"OLD_A": {"HGNC:1"}}
        _previous = {"PREV_A": {"HGNC:1"}}
        _ensembl = {"ENSG00000123456": {"HGNC:1"}}
        _withdrawn = {"OLD_X": []}

        def __init__(self, complete_path, withdrawn_path, *, release):
            assert release == HGNC_ARCHIVE_RELEASE
            self.complete_sha256 = _sha(complete_path)
            self.withdrawn_sha256 = _sha(withdrawn_path)

    monkeypatch.setattr(resource_qualification, "HGNCResolver", FakeResolver)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Resource.__table__, ResourceStaging.__table__, ResourceQualification.__table__],
    )
    try:
        with Session(engine) as db:
            resource, staging, qualification, result = register_and_qualify_hgnc_release(
                db,
                acquisition_directory=acquisition,
                managed_directory=managed,
            )
            assert result.passed is True
            assert resource.status == "QUALIFIED"
            assert staging.status == "STAGED"
            assert qualification.status == "QUALIFIED"
            assert Path(resource.location).is_file()
            assert (managed / "hgnc_complete_set.txt").read_bytes() == (
                acquisition / "hgnc_complete_set.txt"
            ).read_bytes()
            assert (managed / "withdrawn.txt").read_bytes() == (
                acquisition / "withdrawn.txt"
            ).read_bytes()
            db.commit()

            persisted_resource = db.scalar(select(Resource).where(Resource.id == resource.id))
            persisted_qualification = db.scalar(
                select(ResourceQualification).where(
                    ResourceQualification.resource_id == resource.id,
                    ResourceQualification.qualification_version == "siraloom-hgnc-2026-10-06-v1",
                )
            )
            assert persisted_resource.status == "QUALIFIED"
            assert persisted_qualification.status == "QUALIFIED"
    finally:
        engine.dispose()
