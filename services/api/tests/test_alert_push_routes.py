"""The browser notification routes for critical alerts are for a signed-in person, never an API key (like the older push gateway), and refuse a non-https address."""

import uuid

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import alert_push
from fastapi import FastAPI
from fastapi.testclient import TestClient

P = alert_push.router.prefix
BODY = {"endpoint": "https://push.example.net/x", "keys": {"p256dh": "A" * 40, "auth": "B" * 12}}
ROUTES = [("GET", f"{P}/public-key", None), ("POST", f"{P}/subscribe", BODY), ("POST", f"{P}/unsubscribe", {"endpoint": BODY["endpoint"]}), ("POST", f"{P}/test", {})]


def client(scopes):
    app = FastAPI()
    app.include_router(alert_push.router)
    app.dependency_overrides[deps.get_current_user] = lambda: deps.CurrentUser(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="admin", email="o@example.com", scopes=scopes)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("scopes", [["*"], ["alerts:read"], []], ids=["full key", "read key", "scopeless key"])
@pytest.mark.parametrize("method, path, body", ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_an_api_key_is_refused(method, path, body, scopes):
    r = client(scopes).request(method, path, json=body)
    assert r.status_code == 403 and ("not an API key" in r.json()["detail"] or "missing scope" in r.json()["detail"])


def test_a_plain_http_push_address_is_refused_before_the_database_is_touched():
    r = client(None).post(f"{P}/subscribe", json={**BODY, "endpoint": "http://push.example.net/x"})
    assert r.status_code == 422 and "https" in r.json()["detail"]
