def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_evidence_routes_registered(client):
    paths = {route.path for route in client.app.routes}
    assert "/api/v1/analyses/{analysis_id}/evidence" in paths
    assert "/api/v1/evidence/{evidence_id}" in paths
