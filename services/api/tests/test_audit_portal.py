"""The auditor sign-in and the files an audit keeps: an auditor reaches only /audit-portal and only the audits linked to them.

Pure checks first (the role, every route the application has, the file rules), then the portal and the staff routes against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable
fully migrated database), because the question is what row-level security and the cross-tenant read block let through.
"""

import base64
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import audit_portal as ap
from app.api.v1.endpoints import audits as au
from app.core.security import ROLE_PERMISSIONS, has_permission, known_permissions
from app.db.rls import set_rls_context
from app.main import app
from app.services import client_portal as cp
from fastapi import HTTPException
from route_introspect import required_permissions, walk_routes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ALL_ROUTES = list(walk_routes(app.routes))
ALL_METHOD_PATHS = sorted({(m, p) for p, r in ALL_ROUTES for m in r.methods if m not in {"HEAD", "OPTIONS"}})


def fake_request(method: str, path: str, headers: dict | None = None):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers or {}, cookies={}, state=SimpleNamespace())


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ----------------------------------------------------------------------------- the role and the reach (pure)


def test_the_auditor_holds_one_permission_that_no_staff_role_holds_and_nothing_else():
    assert ROLE_PERMISSIONS["auditor"] == ["audit_portal:view"]
    for p in known_permissions() - {"audit_portal:view"}:
        assert not has_permission("auditor", p), p
    for role, perms in ROLE_PERMISSIONS.items():
        if role not in {"auditor", "platform_admin", "admin"}:
            assert "audit_portal:view" not in perms, role


def test_no_route_is_open_to_the_auditor_by_its_own_permission_check_except_the_audit_pages():
    reachable = sorted(
        {
            path
            for path, route in ALL_ROUTES
            if (needed := set(required_permissions(route))) and all(has_permission("auditor", p) for p in needed)
        }
    )
    assert reachable and all(p.startswith("/api/v1/audit-portal/") for p in reachable), reachable


@pytest.mark.parametrize("method,path", ALL_METHOD_PATHS)
def test_every_route_of_the_application_but_the_audit_pages_and_own_sign_in_refuses_the_auditor(method, path):
    rel = cp.relative_path(path)
    full = "/api/v1" + rel if not path.startswith("/api/") else path
    should_pass = rel.startswith("/audit-portal/") or (method, rel) in (cp.ALLOWED_PATHS - {("GET", "/client-portal/summary")})
    if should_pass:
        cp.enforce_reach("auditor", fake_request(method, full))
    else:
        with pytest.raises(HTTPException) as e:
            cp.enforce_reach("auditor", fake_request(method, full))
        assert e.value.status_code == 403
    cp.enforce_reach("tenant_admin", fake_request(method, full))  # staff are not affected
    if rel.startswith("/audit-portal/"):
        with pytest.raises(HTTPException):
            cp.enforce_reach("client_viewer", fake_request(method, full))  # the customer sign-in cannot open the audit pages


def test_an_auditor_cannot_view_another_tenant_or_turn_off_the_second_factor():
    with pytest.raises(HTTPException):
        cp.enforce_reach("auditor", fake_request("GET", "/api/v1/audit-portal/audits", {"x-view-as-tenant": str(uuid.uuid4())}))
    with pytest.raises(HTTPException):
        cp.enforce_reach("auditor", fake_request("POST", "/api/v1/auth/totp/disable"))
    with pytest.raises(HTTPException):
        cp.enforce_reach("auditor", fake_request("GET", "/api/v1/audit-portal"))  # only paths below it


def test_file_names_lose_folders_and_odd_characters_and_are_never_empty():
    assert ap.clean_file_name("C:\\evidence\\..\\report 2026.pdf") == "report 2026.pdf"
    assert ap.clean_file_name("../../etc/passwd") == "passwd"
    assert ap.clean_file_name('a"b<c>.txt') == "a_b_c_.txt"
    assert ap.clean_file_name("  ...  ") == "file"
    assert len(ap.clean_file_name("x" * 400)) == 255


def test_uploads_must_be_real_base64_not_empty_and_at_most_ten_megabytes():
    assert ap.decode_content(b64(b"hello")) == b"hello"
    for bad in ("not base64 !!", ""):
        with pytest.raises(HTTPException) as e:
            ap.decode_content(bad)
        assert e.value.status_code == 422
    with pytest.raises(HTTPException) as empty:
        ap.decode_content(b64(b""))  # an empty string is rejected at validation; zero bytes are rejected here
    assert empty.value.status_code == 422
    with pytest.raises(HTTPException) as big:
        ap.decode_content(b64(b"x" * (ap.MAX_FILE_BYTES + 1)))
    assert big.value.status_code == 413
    assert len(ap.decode_content(b64(b"x" * ap.MAX_FILE_BYTES))) == ap.MAX_FILE_BYTES


def test_a_download_is_always_an_attachment_of_unknown_type():
    f = SimpleNamespace(content=b"<html><script>alert(1)</script>", name="x.html")
    r = ap._download(f)  # type: ignore[arg-type]
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


# ----------------------------------------------------------------------------- against a real Postgres

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    msp, other = uuid.uuid4(), uuid.uuid4()
    audit_a, audit_b, audit_other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    req_a = uuid.uuid4()
    users = SimpleNamespace(auditor=uuid.uuid4(), auditor2=uuid.uuid4(), stranger=uuid.uuid4(), staff=uuid.uuid4())
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, n in ((msp, "msp"), (other, "other")):
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ap-{n}", "s": f"ap-{n}-{tid.hex[:8]}"})
        for who, tid, role in (("auditor", msp, "auditor"), ("auditor2", msp, "auditor"), ("stranger", other, "auditor"), ("staff", msp, "tenant_admin")):
            uid = getattr(users, who)
            await conn.execute(
                text("insert into users (id, tenant_id, email, account_name, username, hashed_password, role, is_active) values (:i,:t,:e,:a,:u,'x',:r,true)"),
                {"i": uid, "t": tid, "e": f"{who}-{uid.hex[:6]}@x.test", "a": f"ap{uid.hex[:12]}", "u": who, "r": role},
            )
        for aid, tid, name in ((audit_a, msp, "SOC 2 2026"), (audit_b, msp, "ISO 2026"), (audit_other, other, "Other audit")):
            await conn.execute(
                text("insert into audits (id, tenant_id, name, framework, status) values (:i,:t,:n,'SOC2','fieldwork')"), {"i": aid, "t": tid, "n": name}
            )
        await conn.execute(
            text("insert into audit_requests (id, tenant_id, audit_id, title, status) values (:i,:t,:a,'Access review evidence','provided')"),
            {"i": req_a, "t": msp, "a": audit_a},
        )
    w = SimpleNamespace(msp=msp, other=other, audit_a=audit_a, audit_b=audit_b, audit_other=audit_other, req_a=req_a, users=users, engine=engine)
    w.emails = {}
    async with engine.begin() as conn:
        for who in ("auditor", "auditor2", "stranger"):
            row = (await conn.execute(text("select email from users where id = :i"), {"i": getattr(users, who)})).scalar_one()
            w.emails[who] = row
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (msp, other):
            for table in ("audit_files", "audit_auditors", "audit_requests", "audits"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from users where tenant_id = any(:t)"), {"t": [msp, other]})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [msp, other]})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


def staff_of(w):
    return SimpleNamespace(tenant_id=w.msp, user_id=w.users.staff, email="hal@goliveoak.com", role="tenant_admin", require_permission=lambda p: None)


def auditor_of(w, who="auditor", tenant=None):
    return SimpleNamespace(user_id=getattr(w.users, who), tenant_id=tenant or w.msp, email=w.emails[who], role="auditor")


@needs_pg
@pytest.mark.asyncio
async def test_staff_link_an_auditor_and_the_auditor_sees_only_that_audit(world):
    w = world
    staff = staff_of(w)
    linked = await run(w.msp, lambda db: ap.add_auditor(w.audit_a, ap.AuditorIn(email=w.emails["auditor"].upper()), w.msp, db, staff))
    assert [a.email for a in linked] == [w.emails["auditor"]]
    again = await run(w.msp, lambda db: ap.add_auditor(w.audit_a, ap.AuditorIn(email=w.emails["auditor"]), w.msp, db, staff))
    assert len(again) == 1, "linking twice does not duplicate"

    mine = await run(w.msp, lambda db: ap.my_audits(auditor_of(w), db))
    assert [a.name for a in mine] == ["SOC 2 2026"]
    detail = await run(w.msp, lambda db: ap.my_audit(w.audit_a, auditor_of(w), db))
    assert [i.title for i in detail.items] == ["Access review evidence"]
    for other_audit in (w.audit_b, w.audit_other):
        with pytest.raises(HTTPException) as e:
            await run(w.msp, lambda db, a=other_audit: ap.my_audit(a, auditor_of(w), db))
        assert e.value.status_code == 404
    assert await run(w.msp, lambda db: ap.my_audits(auditor_of(w, "auditor2"), db)) == [], "an auditor with no link sees nothing"

    gone = await run(w.msp, lambda db: ap.remove_auditor(w.audit_a, w.users.auditor, w.msp, db, staff))
    assert gone == []
    assert await run(w.msp, lambda db: ap.my_audits(auditor_of(w), db)) == []


@needs_pg
@pytest.mark.asyncio
async def test_only_a_person_with_the_auditor_role_in_the_callers_workspace_can_be_linked(world):
    w = world
    staff = staff_of(w)
    for email in (w.emails["stranger"], "nobody@x.test"):  # another workspace's auditor, and an address nobody has
        with pytest.raises(HTTPException) as e:
            await run(w.msp, lambda db, m=email: ap.add_auditor(w.audit_a, ap.AuditorIn(email=m), w.msp, db, staff))
        assert e.value.status_code == 404
    async with w.engine.begin() as conn:
        staff_email = (await conn.execute(text("select email from users where id = :i"), {"i": w.users.staff})).scalar_one()
    with pytest.raises(HTTPException) as notauditor:
        await run(w.msp, lambda db: ap.add_auditor(w.audit_a, ap.AuditorIn(email=staff_email), w.msp, db, staff))
    assert notauditor.value.status_code == 404, "a staff account cannot be linked as an auditor"


@needs_pg
@pytest.mark.asyncio
async def test_files_are_added_by_staff_and_by_the_auditor_downloaded_and_kept_to_their_rules(world):
    w = world
    staff = staff_of(w)
    await run(w.msp, lambda db: ap.add_auditor(w.audit_a, ap.AuditorIn(email=w.emails["auditor"]), w.msp, db, staff))
    listed = await run(w.msp, lambda db: ap.upload_file(w.audit_a, ap.FileIn(name="../policy.pdf", content_base64=b64(b"PDF-1"), request_id=w.req_a), w.msp, db, staff))
    assert [(f.name, f.size_bytes, f.by_auditor) for f in listed] == [("policy.pdf", 5, False)]
    mine = await run(w.msp, lambda db: ap.my_upload(w.audit_a, ap.FileIn(name="questions.txt", content_base64=b64(b"more please")), auditor_of(w), db))
    assert sorted((f.name, f.by_auditor) for f in mine) == [("policy.pdf", False), ("questions.txt", True)]
    the_file = next(f for f in mine if f.by_auditor)
    dl = await run(w.msp, lambda db: ap.my_download(w.audit_a, the_file.id, auditor_of(w), db))
    assert dl.body == b"more please"
    assert (await run(w.msp, lambda db: ap.download_file(w.audit_a, the_file.id, w.msp, db, staff))).body == b"more please"

    # not their audit: an upload or a read is "not found", and the file is not reachable through another audit's id
    with pytest.raises(HTTPException) as up:
        await run(w.msp, lambda db: ap.my_upload(w.audit_b, ap.FileIn(name="x.txt", content_base64=b64(b"x")), auditor_of(w), db))
    assert up.value.status_code == 404
    with pytest.raises(HTTPException) as cross:
        await run(w.msp, lambda db: ap.download_file(w.audit_b, the_file.id, w.msp, db, staff))
    assert cross.value.status_code == 404
    with pytest.raises(HTTPException) as badreq:
        await run(w.msp, lambda db: ap.upload_file(w.audit_a, ap.FileIn(name="y.txt", content_base64=b64(b"y"), request_id=uuid.uuid4()), w.msp, db, staff))
    assert badreq.value.status_code == 404

    left = await run(w.msp, lambda db: ap.delete_file(w.audit_a, the_file.id, w.msp, db, staff))
    assert [f.name for f in left] == ["policy.pdf"]


@needs_pg
@pytest.mark.asyncio
async def test_a_complete_audit_takes_no_more_files_and_the_auditor_can_accept_what_was_provided(world):
    w = world
    staff = staff_of(w)
    await run(w.msp, lambda db: ap.add_auditor(w.audit_a, ap.AuditorIn(email=w.emails["auditor"]), w.msp, db, staff))
    accepted = await run(w.msp, lambda db: ap.my_request(w.audit_a, w.req_a, ap.AuditorRequestPatch(status="accepted", note="Looks complete"), auditor_of(w), db))
    item = accepted.items[0]
    assert item.status == "accepted" and "Looks complete" in item.note and "Auditor (" in item.note
    sent_back = await run(w.msp, lambda db: ap.my_request(w.audit_a, w.req_a, ap.AuditorRequestPatch(status="open", note="Need the March list"), auditor_of(w), db))
    assert sent_back.items[0].status == "open", "sending it back means staff must provide again"

    async with w.engine.begin() as conn:
        await conn.execute(text("update audits set status = 'complete' where id = :i"), {"i": w.audit_a})
    for work in (
        lambda db: ap.my_upload(w.audit_a, ap.FileIn(name="late.txt", content_base64=b64(b"x")), auditor_of(w), db),
        lambda db: ap.upload_file(w.audit_a, ap.FileIn(name="late.txt", content_base64=b64(b"x")), w.msp, db, staff),
        lambda db: ap.my_request(w.audit_a, w.req_a, ap.AuditorRequestPatch(status="accepted"), auditor_of(w), db),
    ):
        with pytest.raises(HTTPException) as e:
            await run(w.msp, work)
        assert e.value.status_code == 409


@needs_pg
@pytest.mark.asyncio
async def test_the_audit_pages_refuse_anyone_who_is_not_an_auditor_with_the_second_factor(world):
    w = world
    staff_user = SimpleNamespace(role="tenant_admin", scopes=None, viewing_other_tenant=False, user_id=w.users.staff, tenant_id=w.msp, require_permission=lambda p: None)
    with pytest.raises(HTTPException) as e:
        await run(w.msp, lambda db: ap.auditor_user(staff_user, db))
    assert e.value.status_code == 403
    aud = SimpleNamespace(role="auditor", scopes=None, viewing_other_tenant=False, user_id=w.users.auditor, tenant_id=w.msp, require_permission=lambda p: None)
    with pytest.raises(HTTPException) as nomfa:
        await run(w.msp, lambda db: ap.auditor_user(aud, db))
    assert nomfa.value.status_code == 403 and "mfa_setup_required" in str(nomfa.value.detail)
    key = SimpleNamespace(**{**vars(aud), "scopes": ["audit_portal:view"]})
    with pytest.raises(HTTPException) as apikey:
        await run(w.msp, lambda db: ap.auditor_user(key, db))
    assert apikey.value.status_code == 403


@needs_pg
@pytest.mark.asyncio
async def test_staff_can_create_an_auditor_sign_in_that_opens_only_the_audit_it_was_made_for(world):
    w = world
    staff = staff_of(w)
    out = await run(w.msp, lambda db: ap.invite_auditor(w.audit_a, ap.InviteIn(account_name="pat-audit", email="pat@auditfirm.test", name="Pat"), w.msp, db, staff))
    assert [a.email for a in out.auditors] == ["pat@auditfirm.test"] and len(out.temporary_password) >= 15
    async with w.engine.begin() as conn:
        row = (await conn.execute(text("select id, role, hashed_password, is_active from users where email = 'pat@auditfirm.test'"))).one()
    assert row.role == "auditor" and row.is_active and row.hashed_password != out.temporary_password and out.temporary_password not in row.hashed_password
    pat = SimpleNamespace(user_id=row.id, tenant_id=w.msp, email="pat@auditfirm.test", role="auditor")
    assert [a.name for a in await run(w.msp, lambda db: ap.my_audits(pat, db))] == ["SOC 2 2026"]
    with pytest.raises(HTTPException) as other_audit:
        await run(w.msp, lambda db: ap.my_audit(w.audit_b, pat, db))
    assert other_audit.value.status_code == 404
    for body in (ap.InviteIn(account_name="pat-audit"), ap.InviteIn(account_name="pat-two", email="PAT@auditfirm.test")):
        with pytest.raises(HTTPException) as dup:
            await run(w.msp, lambda db, b=body: ap.invite_auditor(w.audit_a, b, w.msp, db, staff))
        assert dup.value.status_code == 409
    with pytest.raises(HTTPException) as bad:
        await run(w.msp, lambda db: ap.invite_auditor(w.audit_a, ap.InviteIn(account_name="no spaces allowed!"), w.msp, db, staff))
    assert bad.value.status_code == 422
