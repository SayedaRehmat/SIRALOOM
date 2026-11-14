import hashlib
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ARTIFACT_ROOT", str(Path(tempfile.gettempdir()) / "siraloom-tests"))
os.environ.setdefault("GENEBE_ENABLED", "false")

from backend.app.main import app  # noqa: E402, I001

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def stub_ebi_validator_for_unit_tests(monkeypatch):
    """Keep ordinary unit tests independent of the separately qualified EBI binary."""
    from backend.app.domain import ingestion

    def fake_validator(path, **kwargs):
        source = Path(path)
        fileformat = None
        opener = __import__("gzip").open if source.name.lower().endswith((".gz", ".bgz")) else open
        with opener(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("##fileformat="):
                    fileformat = line.rstrip("\\r\\n").split("=", 1)[1]
                    break
                if line.startswith("#CHROM"):
                    break
        caller = kwargs.get("caller_provenance") or {}
        return {
            "validator": "EBI_VCF_VALIDATION_SUITE",
            "validator_version_expected": "0.10.2",
            "validator_profile_id": "unit-test-stub",
            "artifact_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "vcf_version": fileformat,
            "caller": caller.get("caller_profile_id", "UNKNOWN"),
            "caller_provenance": caller,
            "status": "PASS",
            "reports": [],
            "report_count": 0,
        }

    monkeypatch.setattr(ingestion, "run_ebi_vcf_validator", fake_validator)
