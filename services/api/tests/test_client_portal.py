"""The customer-facing dashboard sign-in (/client-portal): a client_viewer sees ONLY their own company's numbers, reaches no other route, and gets nothing without an authenticator app.

Pure checks first (the role, and every route the application has), then the portal and the staff routes against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database),
because the question is what row-level security and the cross-tenant read block let through.
"""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import client_portal as ep
from app.core.security import ROLE_PERMISSIONS, has_permission, known_permissions
from app.db.rls import set_rls_context
from app.main import app
from app.models.user_totp import UserTotp
from app.services import client_portal as cp
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from route_introspect import required_permissions, walk_routes
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ALL_ROUTES = list(walk_routes(app.routes))
ALL_METHOD_PATHS = sorted({(m, p) for p, r in ALL_ROUTES for m in r.methods if m not in {"HEAD", "OPTIONS"}})


def fake_request(method: str, path: str, headers: dict | None = None):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers or {}, cookies={}, state=SimpleNamespace())


# ----------------------------------------------------------------------------- the role and the reach (pure)


def test_the_client_viewer_holds_one_permission_that_no_staff_role_holds_and_nothing_else():
    assert ROLE_PERMISSIONS["client_viewer"] == ["client_portal:view"]
    for p in known_permissions() - {"client_portal:view"}:
        assert not has_permission("client_viewer", p), p
    for role, perms in ROLE_PERMISSIONS.items():
        if role not in {"client_viewer", "platform_admin", "admin"}:
            assert "client_portal:view" not in perms, role  # only the wildcard roles hold it, through "*"


def test_a_workspace_administrator_cannot_hand_out_the_client_role():
    admin = deps.CurrentUser(uuid.uuid4(), uuid.uuid4(), "tenant_admin", "a@x")
    assert not admin.can_grant_role("client_viewer")


def test_no_route_is_open_to_the_client_role_by_its_own_permission_check():
    reachable = [
        (path, sorted(route.methods))
        for path, route in ALL_ROUTES
        if (needed := set(required_permissions(route))) and all(has_permission("client_viewer", p) for p in needed)
    ]
    assert [p for p, _ in reachable] == ["/api/v1/client-portal/summary"]  # the portal itself, and nothing else


def test_the_allowed_routes_all_exist_and_are_exactly_the_portal_and_the_clients_own_sign_in():
    existing = {(m, cp.relative_path(p)) for m, p in ALL_METHOD_PATHS}
    assert set(cp.ALLOWED_PATHS) <= existing, set(cp.ALLOWED_PATHS) - existing
    assert {p for _, p in cp.ALLOWED_PATHS if not p.startswith("/auth/")} == {"/client-portal/summary"}
    assert ("POST", "/auth/totp/disable") not in cp.ALLOWED_PATHS and ("POST", "/auth/totp/recovery") not in cp.ALLOWED_PATHS


@pytest.mark.parametrize("method,path", ALL_METHOD_PATHS)
def test_every_other_route_of_the_application_refuses_the_client_role(method, path):
    allowed = (method, cp.relative_path(path)) in cp.ALLOWED_PATHS
    full = "/api/v1" + cp.relative_path(path) if not path.startswith("/api/") else path
    if allowed:
        cp.enforce_reach("client_viewer", fake_request(method, full))
    else:
        with pytest.raises(HTTPException) as e:
            cp.enforce_reach("client_viewer", fake_request(method, full))
        assert e.value.status_code == 403
    cp.enforce_reach("tenant_admin", fake_request(method, full))  # staff are not affected


def test_a_client_cannot_ask_to_view_another_tenant_even_on_the_portal_route():
    with pytest.raises(HTTPException) as e:
        cp.enforce_reach("client_viewer", fake_request("GET", "/api/v1/client-portal/summary", {"x-view-as-tenant": str(uuid.uuid4())}))
    assert e.value.status_code == 403


@pytest.mark.parametrize(
    "path",
    ["/api/v1/reports/ticket-metrics", "/api/v1/alerts", "/api/v1/tenants/me/users", "/api/v1/api-keys", "/api/v1/auth/totp/disable"],
)
async def test_get_current_user_refuses_a_client_on_a_staff_route_before_anything_else(monkeypatch, path):
    """The wiring: the gate runs inside get_current_user, so a route that checks no permission of its own is refused too."""
    client = deps.CurrentUser(uuid.uuid4(), uuid.uuid4(), "client_viewer", "c@x")

    async def fake_authenticate(credentials, db):
        return client

    monkeypatch.setattr(deps, "_authenticate", fake_authenticate)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    with pytest.raises(HTTPException) as e:
        await deps.get_current_user(creds, db=None, request=fake_request("GET", path))
    assert e.value.status_code == 403


async def test_get_current_user_lets_a_client_reach_the_portal_route(monkeypatch):
    client = deps.CurrentUser(uuid.uuid4(), uuid.uuid4(), "client_viewer", "c@x")

    async def fake_authenticate(credentials, db):
        return client

    async def no_tag(db, tenant_id):
        return None

    monkeypatch.setattr(deps, "_authenticate", fake_authenticate)
    monkeypatch.setattr(deps, "tag_session", no_tag)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    got = await deps.get_current_user(creds, db=None, request=fake_request("GET", "/api/v1/client-portal/summary"))
    assert got is client


def test_the_portal_route_depends_on_the_client_check_and_no_route_takes_a_client_from_the_request():
    route = next(r for p, r in ALL_ROUTES if p.endswith("/client-portal/summary"))
    assert {d.call for d in route.dependant.dependencies} >= {ep.client_portal_user}
    names = (
        {q.name for q in route.dependant.query_params}
        | {q.name for q in route.dependant.path_params}
        | {h.name for h in route.dependant.header_params}
    )
    assert names == {"months"}


def test_a_name_that_cannot_be_matched_safely_gets_no_hours_or_satisfaction():
    payload = {
        "rows": [
            {"client_id": "1", "client_name": "Acme Dental"},
            {"client_id": "2", "client_name": "ACME dental."},
            {"client_id": "3", "client_name": ""},
        ]
    }
    assert not cp._name_is_safe("Acme Dental", payload, "1")  # another client has the same name once case and punctuation are ignored
    assert not cp._name_is_safe("", payload, "3")  # an empty name would match EVERY client in the hours and the survey
    assert not cp._name_is_safe("  -- ", payload, "3")
    assert cp._name_is_safe("Birch Law", payload, "9")


# ----------------------------------------------------------------------------- against a real Postgres

PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)

MONTH = "2026-10"


def stats_row(client, name, created, resolved):
    return {
        "client_id": client,
        "client_name": name,
        "month": MONTH,
        "created": created,
        "resolved": resolved,
        "responded": created,
        "response_minutes": created * 10.0,
        "created_by_type": {"Incident": created},
        "resolved_by_agent": {"40": resolved},
        "critical": 0,
        "high": 0,
    }


@pytest.fixture
async def world():
    ids = SimpleNamespace(**{n: uuid.uuid4() for n in ("msp", "other_msp", "acme", "birch", "unmapped", "crossed", "twin_a", "twin_b")})
    users = SimpleNamespace(
        **{n: uuid.uuid4() for n in ("acme", "acme_nomfa", "birch", "unmapped", "crossed", "staff", "boss", "boss_other")}
    )
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for name, tid in vars(ids).items():
            parent = ids.msp if name in {"acme", "birch", "unmapped", "crossed", "twin_a", "twin_b"} else None
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"),
                {"i": tid, "n": f"{name} co", "s": f"cp-{tid.hex[:10]}", "p": parent},
            )
        for who, tid, role in (
            ("acme", ids.acme, "client_viewer"),
            ("acme_nomfa", ids.acme, "client_viewer"),
            ("birch", ids.birch, "client_viewer"),
            ("unmapped", ids.unmapped, "client_viewer"),
            ("crossed", ids.crossed, "client_viewer"),
            ("staff", ids.acme, "viewer"),
            ("boss", ids.msp, "tenant_admin"),
            ("boss_other", ids.other_msp, "tenant_admin"),
        ):
            uid = getattr(users, who)
            await conn.execute(
                text(
                    "insert into users (id, tenant_id, account_name, username, hashed_password, role, is_active) values (:i,:t,:a,:u,'x',:r,true)"
                ),
                {"i": uid, "t": tid, "a": f"cp{uid.hex[:12]}", "u": who, "r": role},
            )
        for who in ("acme", "birch", "unmapped", "crossed"):
            await conn.execute(
                text(
                    "insert into user_totp (user_id, tenant_id, secret_enc, confirmed_at, recovery_hashes) values (:u, :t, 'x', now(), '[]'::jsonb)"
                ),
                {"u": getattr(users, who), "t": getattr(ids, who)},
            )
        alias = (
            "insert into client_aliases (id, tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id) "
            "values (gen_random_uuid(), :o, :v, :c, :n, :nn, :ch)"
        )
        for owner, vendor, cid, name, child in (
            (ids.msp, "halopsa", "57", "Acme Dental", ids.acme),
            (ids.msp, "halopsa", "58", "Birch Law", ids.birch),
            (ids.msp, "huntress", "h9", "Unrelated Huntress", ids.unmapped),  # another vendor's mapping is not a HaloPSA client
            (ids.other_msp, "halopsa", "77", "Crossed", ids.crossed),  # an alias owned by someone who is NOT the customer's parent
        ):
            await conn.execute(text(alias), {"o": owner, "v": vendor, "c": cid, "n": name, "nn": name.lower(), "ch": child})
        tickets = {
            "months": [MONTH],
            "rows": [
                stats_row("57", "Acme Dental", 11, 9),
                stats_row("58", "Birch Law", 400, 390),
                stats_row("59", "Twin", 5, 5),
                stats_row("60", "TWIN.", 6, 6),
            ],
            "open_now": [
                {"client_id": "57", "client_name": "Acme Dental", "total": 3, "critical": 1, "high": 0},
                {"client_id": "58", "client_name": "Birch Law", "total": 70, "critical": 7, "high": 7},
            ],
        }
        hours = {
            "months": [MONTH],
            "agents": [{"id": "40", "name": "Engineer One"}],
            "hours": [
                {"month": MONTH, "client": "Acme Dental", "agent_id": "40", "hours": 12.5, "charge_type": "Support"},
                {"month": MONTH, "client": "Birch Law", "agent_id": "40", "hours": 999.0, "charge_type": "Support"},
            ],
        }
        csat = {
            "months": [MONTH],
            "rows": [
                {"month": MONTH, "company": "Acme Dental", "positive": 4, "neutral": 0, "negative": 1, "total": 5},
                {"month": MONTH, "company": "Birch Law", "positive": 0, "neutral": 0, "negative": 50, "total": 50},
            ],
            "recent": [
                {
                    "date": f"{MONTH}-03",
                    "company": "Acme Dental",
                    "contact": "Ann",
                    "sentiment": "positive",
                    "rating": "Great",
                    "comment": "Quick fix",
                },
                {
                    "date": f"{MONTH}-04",
                    "company": "Birch Law",
                    "contact": "Bob",
                    "sentiment": "negative",
                    "rating": "Bad",
                    "comment": "BIRCH SECRET COMMENT",
                },
            ],
        }
        import json

        for table, payload in (("ticket_stats_snapshots", tickets), ("finance_profit_snapshots", hours), ("csat_snapshots", csat)):
            await conn.execute(
                text(f"insert into {table} (tenant_id, payload, received_at) values (:t, cast(:p as jsonb), now())"),
                {"t": ids.msp, "p": json.dumps(payload)},
            )
    yield SimpleNamespace(ids=ids, users=users)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        every = list(vars(ids).values())
        for table in ("ticket_stats_snapshots", "finance_profit_snapshots", "csat_snapshots", "client_aliases", "user_totp", "audit_log"):
            await conn.execute(text(f"delete from {table} where tenant_id = any(:t)"), {"t": every})
        await conn.execute(text("delete from users where tenant_id = any(:t)"), {"t": every})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": every})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


def client_user(w, who, tenant):
    return deps.CurrentUser(getattr(w.users, who), getattr(w.ids, tenant), "client_viewer", f"{who}@x")


async def portal(w, who, tenant, months=3):
    user = client_user(w, who, tenant)

    async def work(db):
        checked = await ep.client_portal_user(user, db)
        return await ep.portal_summary(checked, db, months)

    return await with_db(user.tenant_id, work)


@needs_pg
async def test_a_client_sees_their_own_numbers_and_none_of_another_clients(world):
    mine = await portal(world, "acme", "acme")
    assert mine["client_name"] == "Acme Dental"
    assert (mine["tickets"]["created"], mine["tickets"]["resolved"]) == (11, 9)
    assert mine["tickets"]["open_now"] == {"total": 3, "critical": 1, "high": 0}
    assert mine["hours"]["total_hours"] == 12.5
    assert (mine["satisfaction"]["responses"], mine["satisfaction"]["negative"]) == (5, 1)
    assert set(mine["hours"]) == {"months", "total_hours", "hours_per_month", "by_month", "by_type"}
    text_of_it = repr(mine)
    for other in ("Birch", "BIRCH SECRET", "999", "Twin", "clients", "by_client"):
        assert other not in text_of_it, other
    theirs = await portal(world, "birch", "birch")
    assert (theirs["tickets"]["created"], theirs["hours"]["total_hours"], theirs["satisfaction"]["responses"]) == (400, 999.0, 50)
    assert "Acme" not in repr(theirs)


@needs_pg
async def test_nothing_the_caller_sends_can_change_which_client_is_shown(world):
    """The route has one parameter, months; the client comes from the signed-in user's own tenant. The same user asking for different periods always gets only their own client."""
    for months in (1, 6, 12):
        got = await portal(world, "acme", "acme", months)
        assert got["client_name"] == "Acme Dental" and "Birch" not in repr(got)


@needs_pg
async def test_a_client_whose_tenant_has_no_halopsa_link_gets_nothing(world):
    for who in ("unmapped", "crossed"):  # a Huntress-only mapping; an alias owned by a different MSP than the customer's parent
        with pytest.raises(HTTPException) as e:
            await portal(world, who, who)
        assert e.value.status_code == 409, who


@needs_pg
async def test_a_name_shared_by_two_clients_gets_tickets_by_id_but_no_hours_or_satisfaction(world):
    async def work(db):
        client = cp.PortalClient(world.ids.twin_a, world.ids.msp, "59", "Twin")
        return await cp.summary(db, client, 3)

    got = await with_db(world.ids.twin_a, work)
    assert got["tickets"]["created"] == 5  # exact by id: not 11
    assert got["hours"] is None and got["satisfaction"] is None


@needs_pg
async def test_the_portal_refuses_without_an_authenticator_app(world):
    with pytest.raises(HTTPException) as e:
        await portal(world, "acme_nomfa", "acme")
    assert e.value.status_code == 403 and "mfa_setup_required" in e.value.detail

    async def add(db):
        db.add(
            UserTotp(
                user_id=world.users.acme_nomfa, tenant_id=world.ids.acme, secret_enc="x", confirmed_at=datetime.now(UTC), recovery_hashes=[]
            )
        )
        await db.commit()

    await with_db(world.ids.acme, add)
    assert (await portal(world, "acme_nomfa", "acme"))["client_name"] == "Acme Dental"


@needs_pg
async def test_an_unconfirmed_authenticator_setup_does_not_count(world):
    async def unconfirm(db):
        await db.execute(text("update user_totp set confirmed_at = null where user_id = :u"), {"u": world.users.birch})
        await db.commit()

    await with_db(world.ids.birch, unconfirm)
    with pytest.raises(HTTPException) as e:
        await portal(world, "birch", "birch")
    assert e.value.status_code == 403


@needs_pg
async def test_the_portal_refuses_everyone_who_is_not_a_client_session(world):
    async def work(db, user):
        return await ep.client_portal_user(user, db)

    staff = deps.CurrentUser(world.users.staff, world.ids.acme, "viewer", "s@x")
    key = deps.CurrentUser(world.users.acme, world.ids.acme, "client_viewer", "k@x", scopes=["*"])
    viewing = deps.CurrentUser(world.users.acme, world.ids.birch, "client_viewer", "v@x", home_tenant_id=world.ids.acme)
    admin = deps.CurrentUser(world.users.staff, world.ids.acme, "platform_admin", "p@x")
    for user in (staff, key, viewing, admin):
        with pytest.raises(HTTPException) as e:
            await with_db(user.tenant_id, lambda db, u=user: work(db, u))
        assert e.value.status_code == 403


# ----------------------------------------------------------------------------- the MSP's staff routes


def staff(w, tenant="msp"):
    return deps.CurrentUser(w.users.boss if tenant == "msp" else w.users.boss_other, getattr(w.ids, tenant), "tenant_admin", "boss@x")


@needs_pg
async def test_staff_create_a_client_sign_in_for_their_own_mapped_client_and_it_starts_without_a_second_factor(world):
    boss = staff(world)
    body = ep.CreatePortalUser(child_tenant_id=world.ids.birch, account_name="birch.owner", email="owner@birch.example")
    made = await with_db(boss.tenant_id, lambda db: ep.create_portal_user(body, boss, db))
    assert made.temporary_password and len(made.temporary_password) >= 12
    assert made.tenant_id == world.ids.birch and made.client_name == "birch co" and made.mfa_enabled is False

    async def role_of(db):
        return (await db.execute(select(text("role")).select_from(text("users")).where(text("account_name = 'birch.owner'")))).scalar_one()

    assert await with_db(world.ids.birch, role_of) == "client_viewer"
    rows = await with_db(boss.tenant_id, lambda db: ep.list_portal_users(boss, db))
    assert {r.account_name for r in rows} >= {"birch.owner"} and all(
        r.tenant_id in {world.ids.acme, world.ids.birch, world.ids.unmapped, world.ids.crossed} for r in rows
    )


@needs_pg
async def test_staff_cannot_create_or_see_sign_ins_for_a_client_that_is_not_theirs(world):
    other = staff(world, "other_msp")
    body = ep.CreatePortalUser(child_tenant_id=world.ids.acme, account_name="intruder.one")
    with pytest.raises(HTTPException) as e:
        await with_db(other.tenant_id, lambda db: ep.create_portal_user(body, other, db))
    assert e.value.status_code == 404
    seen = await with_db(other.tenant_id, lambda db: ep.list_portal_users(other, db))
    assert {r.id for r in seen}.isdisjoint({world.users.acme, world.users.birch})
    for action in (ep.turn_off_portal_user, ep.reset_portal_user_mfa):
        with pytest.raises(HTTPException) as e:
            await with_db(other.tenant_id, lambda db, a=action: a(world.users.acme, other, db))
        assert e.value.status_code == 404


@needs_pg
async def test_a_client_sign_in_cannot_be_made_for_a_client_with_no_halopsa_link(world):
    boss = staff(world)
    body = ep.CreatePortalUser(child_tenant_id=world.ids.unmapped, account_name="no.link")
    with pytest.raises(HTTPException) as e:
        await with_db(boss.tenant_id, lambda db: ep.create_portal_user(body, boss, db))
    assert e.value.status_code == 409


@needs_pg
async def test_staff_routes_only_touch_client_sign_ins_never_staff_accounts(world):
    boss = staff(world)
    with pytest.raises(HTTPException) as e:
        await with_db(
            boss.tenant_id, lambda db: ep.turn_off_portal_user(world.users.staff, boss, db)
        )  # a staff viewer account inside a managed client
    assert e.value.status_code == 404


@needs_pg
async def test_turning_a_client_sign_in_off_and_resetting_its_second_factor(world):
    boss = staff(world)
    await with_db(boss.tenant_id, lambda db: ep.reset_portal_user_mfa(world.users.acme, boss, db))
    with pytest.raises(HTTPException) as e:
        await portal(world, "acme", "acme")
    assert e.value.status_code == 403 and "mfa_setup_required" in e.value.detail  # closed until they set up a new authenticator app
    await with_db(boss.tenant_id, lambda db: ep.turn_off_portal_user(world.users.birch, boss, db))

    async def active(db):
        return (await db.execute(text("select is_active from users where id = :u"), {"u": world.users.birch})).scalar_one()

    assert await with_db(world.ids.birch, active) is False


def test_the_staff_routes_need_both_permissions_and_are_outside_the_clients_reach():
    for path, route in ALL_ROUTES:
        if "/mssp/client-portal-users" in path:
            assert set(required_permissions(route)) >= {"mssp:manage", "users:write"}, path
            assert not cp.reach_allowed(next(iter(route.methods - {"HEAD", "OPTIONS"})), path)
