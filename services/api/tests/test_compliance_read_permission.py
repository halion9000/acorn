"""compliance:read: the narrow read-only permission CORE's key holds for the compliance skills of the agents (Hal, 2026-11-21).

reports:read still reads everything it did (it implies compliance:read); a key holding only compliance:read reads exactly eight routes and nothing else in the application.
"""

from app.core.security import IMPLIED_BY, known_permissions, permission_in
from app.main import app
from app.scripts.bootstrap_production import CORE_KEY_SCOPES
from route_introspect import required_permissions, walk_routes

EIGHT = {
    ("GET", "/compliance/answer-library"),
    ("GET", "/compliance/questionnaires"),
    ("GET", "/compliance/questionnaires/{questionnaire_id}"),
    ("GET", "/compliance/access-reviews"),
    ("GET", "/compliance/access-reviews/{review_id}"),
    ("GET", "/compliance/vendors"),
    ("GET", "/compliance/vendors/{vendor_id}"),
    ("GET", "/compliance/tests"),
}


def _reachable(granted):
    out = set()
    for full, route in walk_routes(app.routes):
        needed = set(required_permissions(route))
        if needed and all(permission_in(granted, p) for p in needed):
            for m in route.methods - {"HEAD", "OPTIONS"}:
                out.add((m, full.replace("/api/v1", "", 1)))
    return out


def test_reports_read_implies_it_and_it_does_not_imply_reports_read():
    assert IMPLIED_BY["compliance:read"] == ("reports:read",)
    assert permission_in(["reports:read"], "compliance:read") and permission_in(["*"], "compliance:read")
    assert not permission_in(["compliance:read"], "reports:read") and not permission_in(["compliance:read"], "reports:write")
    assert "compliance:read" in known_permissions() and "compliance:read" in CORE_KEY_SCOPES


def test_a_key_with_only_compliance_read_reaches_exactly_the_eight_routes_the_skills_use():
    assert _reachable(["compliance:read"]) == EIGHT


def test_everything_reports_read_could_read_before_is_still_readable_by_it():
    assert EIGHT <= _reachable(["reports:read"])
