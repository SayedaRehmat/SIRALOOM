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

