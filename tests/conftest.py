import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ARTIFACT_ROOT", "/tmp/siraloom-tests")
os.environ.setdefault("GENEBE_ENABLED", "false")

from fastapi.testclient import TestClient
from backend.app.main import app

import pytest

@pytest.fixture
def client():
    return TestClient(app)

