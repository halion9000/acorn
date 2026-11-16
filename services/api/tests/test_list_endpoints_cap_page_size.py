"""Every list endpoint that takes a page size must cap it (roadmap r7-ai-03).

An endpoint that accepts ``limit=1000000`` lets one request read a whole table and its response. This reads the API's own OpenAPI document, so it covers every route
that is registered, including ones added later. The ceiling is the largest cap used today (the audit export, 10000); a new endpoint above it needs a reason.
"""

from __future__ import annotations

from app.main import app

PAGE_SIZE_NAMES = ("limit", "page_size", "per_page", "size", "top", "take")
CEILING = 10_000


def _page_size_params() -> list[tuple[str, str, dict]]:
    found = []
    for path, ops in app.openapi()["paths"].items():
        op = ops.get("get")
        if not op:
            continue
        for p in op.get("parameters", []):
            schema = p.get("schema", {})
            if p["in"] == "query" and p["name"] in PAGE_SIZE_NAMES and (schema.get("type") == "integer" or any(x.get("type") == "integer" for x in schema.get("anyOf", []))):
                found.append((path, p["name"], schema))
    return found


def _maximum(schema: dict) -> int | None:
    if "maximum" in schema:
        return schema["maximum"]
    for x in schema.get("anyOf", []):
        if "maximum" in x:
            return x["maximum"]
    return None


def test_there_are_page_size_parameters_to_check() -> None:
    assert len(_page_size_params()) > 20, "the scan found almost no page-size parameters: it is looking in the wrong place"


def test_every_page_size_has_a_maximum() -> None:
    uncapped = [f"{path} ({name})" for path, name, schema in _page_size_params() if _maximum(schema) is None]
    assert uncapped == [], f"these list endpoints accept any page size: {uncapped}"


def test_no_page_size_maximum_is_above_the_ceiling() -> None:
    too_big = [f"{path} ({name}: {_maximum(schema)})" for path, name, schema in _page_size_params() if (_maximum(schema) or 0) > CEILING]
    assert too_big == [], f"page-size maximum above {CEILING}: {too_big}"

