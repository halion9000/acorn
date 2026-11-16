"""The Policies routes (/governance) are about one client at a time: each takes ``client_id`` like the other compliance routes, and without it they are about the caller's own organization."""

from app.main import app

METHODS = ("get", "post", "patch", "put", "delete")


def _governance_operations() -> list[tuple[str, str, list[str]]]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/governance"):
            continue
        for method, op in ops.items():
            if method in METHODS:
                out.append((method.upper(), path, [p["name"] for p in op.get("parameters", []) if p["in"] == "query"]))
    return out


def test_there_are_governance_routes_to_check() -> None:
    assert len(_governance_operations()) >= 9


def test_every_governance_route_takes_a_client() -> None:
    missing = [f"{m} {p}" for m, p, query in _governance_operations() if "client_id" not in query]
    assert missing == [], f"these Policies routes cannot be pointed at a client: {missing}"
