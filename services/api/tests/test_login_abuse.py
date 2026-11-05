"""The failed sign-in summary: counts only, no typed address named, client addresses with their last part hidden, and the lock thresholds as the throttle has them."""

import asyncio
import contextlib
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from app.api.v1.endpoints import abuse as ep
from app.services.login_abuse import abuse_summary, mask_client


def test_a_client_address_loses_its_last_part_and_a_missing_one_is_unknown():
    assert mask_client("203.0.113.77") == "203.0.113.x"
    assert mask_client("2001:db8:1:2:3:4:5:6") == "2001:db8:1:x"
    assert mask_client(None) == "unknown" and mask_client("") == "unknown" and mask_client("not an address") == "unknown"


def rows(*pairs):
    return list(pairs)


def test_counts_failures_addresses_clients_and_what_is_locked_at_each_limit():
    r = rows(*[("amy@acme.com", "203.0.113.7")] * 5, *[("made-up@x.com", "203.0.113.7")] * 2, ("bob@acme.com", "198.51.100.1"))
    out = abuse_summary(r, per_address=5, per_client=7, window_minutes=15)
    assert (out["failures"], out["addresses_tried"], out["clients"]) == (8, 3, 2)
    assert out["locked_addresses"] == 1, "five for one address is the limit, exactly"
    assert out["locked_clients"] == 1, "seven from one client is the limit, exactly"
    assert out["window_minutes"] == 15


def test_just_under_the_limits_locks_nothing():
    out = abuse_summary(rows(*[("amy@acme.com", "203.0.113.7")] * 4), per_address=5, per_client=5, window_minutes=15)
    assert out["locked_addresses"] == 0 and out["locked_clients"] == 0


def test_the_busiest_clients_are_masked_merged_by_their_masked_form_and_cut_to_five():
    r = rows(*[("a", "203.0.113.7")] * 3, *[("b", "203.0.113.9")] * 2, *[(f"c{i}", f"198.51.{i}.1") for i in range(1, 8)], ("d", None))
    out = abuse_summary(r, 5, 20, 15)
    assert out["busiest_clients"][0] == {"client": "203.0.113.x", "failures": 5}
    assert len(out["busiest_clients"]) == 5
    assert all(c["client"].endswith(".x") for c in out["busiest_clients"]), "no full address leaves the summary"
    assert out["clients"] == 9, "a failure with no client address is not a client"


def test_no_typed_address_appears_anywhere_in_the_summary():
    text = repr(abuse_summary(rows(("amy@acme.com", "203.0.113.7"), ("made-up@x.com", "203.0.113.8")), 5, 20, 15))
    assert "amy" not in text and "made-up" not in text and "203.0.113.7" not in text


def test_the_endpoint_reads_the_window_and_uses_the_throttles_limits(monkeypatch):
    @contextlib.asynccontextmanager
    async def plain(_db):
        yield

    import app.db.rls_scope as scope

    monkeypatch.setattr(scope, "cross_tenant_reads", plain)
    db = MagicMock()

    async def execute(_stmt):
        out = MagicMock()
        out.all.return_value = [("amy@acme.com", "203.0.113.7")] * 5
        return out

    db.execute = execute
    monkeypatch.setattr(ep, "limits", lambda: (5, 20))
    out = asyncio.run(ep.login_abuse(db))
    assert out["failures"] == 5 and out["locked_addresses"] == 1 and out["locked_clients"] == 0


def test_the_route_needs_audit_log_read():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/abuse/logins")])) == {"audit_log:read"}


_ = NS
