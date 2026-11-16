"""The compliance routes' request bodies carry an example in the API document, and every example is a body its route really accepts."""

from __future__ import annotations

from app.core.openapi_examples import EXAMPLES, add_request_examples
from app.core.route_introspect import walk_routes
from app.main import app
from pydantic import TypeAdapter

BODY_METHODS = ("post", "put", "patch")


def _body_routes() -> dict[tuple[str, str], object]:
    found = {}
    for path, route in walk_routes(app.routes):
        for method in getattr(route, "methods", ()) or ():
            if method in ("POST", "PUT", "PATCH") and getattr(route, "body_field", None) is not None:
                found[(method, path)] = route
    return found


def test_every_example_is_a_body_its_route_accepts() -> None:
    routes = _body_routes()
    for key, example in EXAMPLES.items():
        assert key in routes, f"{key} has an example but no such route"
        annotation = routes[key].body_field.field_info.annotation  # type: ignore[attr-defined]
        TypeAdapter(annotation).validate_python(example)


def test_every_compliance_json_body_has_an_example_in_the_document() -> None:
    doc = app.openapi()
    missing = []
    for path, ops in doc["paths"].items():
        if not path.startswith("/api/v1/compliance"):
            continue
        for method, op in ops.items():
            content = (op.get("requestBody") or {}).get("content", {}).get("application/json")
            if method in BODY_METHODS and content is not None and "example" not in content:
                missing.append(f"{method.upper()} {path}")
    assert missing == [], f"these request bodies have no example (add one to app/core/openapi_examples.py): {missing}"


def test_adding_examples_changes_only_the_routes_listed() -> None:
    doc = {
        "paths": {
            "/api/v1/compliance/answer-library": {"post": {"requestBody": {"content": {"application/json": {"schema": {}}}}}},
            "/api/v1/other": {"post": {"requestBody": {"content": {"application/json": {"schema": {}}}}}},
        }
    }
    add_request_examples(doc)
    assert doc["paths"]["/api/v1/compliance/answer-library"]["post"]["requestBody"]["content"]["application/json"]["example"]["category"] == "Data protection"
    assert "example" not in doc["paths"]["/api/v1/other"]["post"]["requestBody"]["content"]["application/json"]
