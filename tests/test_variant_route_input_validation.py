from fastapi.testclient import TestClient

from backend.app.auth.principal import get_current_principal
from backend.app.infrastructure.db.session import get_db
from backend.app.main import app


def test_variant_route_rejects_malformed_uuid_as_validation_error():
    previous_principal = app.dependency_overrides.get(get_current_principal)
    previous_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_current_principal] = lambda: object()
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).get("/api/v1/variants/not-a-uuid")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
        app.dependency_overrides.pop(get_db, None)
        if previous_principal is not None:
            app.dependency_overrides[get_current_principal] = previous_principal
        if previous_db is not None:
            app.dependency_overrides[get_db] = previous_db

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "uuid_parsing"
