"""Structural half of the authorization matrix: every route is classified and guarded by the
dependency its class requires. Runs without a database."""

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.main import ROUTERS
from tests.authz_matrix import GUARDS, MATRIX, SESSION_GUARDS


def _routes() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, r.path): r
        for router in ROUTERS
        for r in router.routes
        if isinstance(r, APIRoute)
        for method in (r.methods or set())
    }


def _guards(dependant: Dependant) -> set[str]:
    names: set[str] = set()
    for dep in dependant.dependencies:
        if dep.call is not None:
            names.add(getattr(dep.call, "__name__", ""))
        names |= _guards(dep)
    return names


def test_every_route_is_in_the_matrix() -> None:
    routes = set(_routes())
    missing = sorted(routes - set(MATRIX))
    stale = sorted(set(MATRIX) - routes)
    assert missing == [], f"routes without an authorization class: {missing}"
    assert stale == [], f"matrix entries for routes that no longer exist: {stale}"


def test_every_route_has_the_guard_its_class_requires() -> None:
    problems = []
    for key, route in _routes().items():
        cls = MATRIX[key]
        present = _guards(route.dependant)
        if not GUARDS[cls] <= present:
            problems.append(f"{key}: {cls} needs {sorted(GUARDS[cls] - present)}")
        if cls in ("public", "public_origin") and present & SESSION_GUARDS:
            problems.append(f"{key}: public route has a session guard")
        if cls not in ("public", "public_origin") and not present & SESSION_GUARDS:
            problems.append(f"{key}: {cls} route has no session guard")
    assert problems == []
