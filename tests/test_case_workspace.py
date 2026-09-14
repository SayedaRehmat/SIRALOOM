def test_case_routes_registered(client):
    paths = {route.path for route in client.app.routes}
    assert "/api/v1/cases" in paths
    assert "/api/v1/cases/{case_id}" in paths
    assert "/api/v1/cases/{case_id}/specimens" in paths


def test_complete_variant_report_routes_registered(client):
    paths = {route.path for route in client.app.routes}
    assert "/api/v1/analyses/{analysis_id}/complete-variant-report" in paths
    assert "/api/v1/analyses/{analysis_id}/complete-variant-report.csv" in paths
    assert "/api/v1/analyses/{analysis_id}/complete-variant-report.json" in paths
