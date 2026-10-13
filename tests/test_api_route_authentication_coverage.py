from fastapi.routing import APIRoute

from backend.app.auth.principal import get_current_principal
from backend.app.main import app


PUBLIC_AUTH_ROUTES = {
    ("POST", "/api/v1/auth/onboarding/organization"),
    ("POST", "/api/v1/auth/onboarding/trial"),
    ("POST", "/api/v1/auth/invitations/accept"),
}
PUBLIC_HEALTH_PATHS = {"/api/v1/health", "/api/v1/ready"}


def _dependency_tree_contains_principal(dependant) -> bool:
    if dependant.call is get_current_principal:
        return True
    return any(
        _dependency_tree_contains_principal(child)
        for child in dependant.dependencies
    )


def test_every_non_public_api_route_requires_server_resolved_principal():
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        methods = route.methods or set()
        if route.path in PUBLIC_HEALTH_PATHS:
            continue
        if all((method, route.path) in PUBLIC_AUTH_ROUTES for method in methods):
            continue
        if not _dependency_tree_contains_principal(route.dependant):
            missing.append(f"{','.join(sorted(methods))} {route.path}")

    assert not missing, (
        "API routes are missing server-resolved authentication or an explicit "
        "public-route exception: " + "; ".join(sorted(missing))
    )
