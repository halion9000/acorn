"""The vendor security questionnaire on a link (r7-af-06): the form and its checking, and the whole flow against Postgres (make a link, open it, answer once, expiry, cancel)."""

import os
import uuid
from types import SimpleNamespace

import pytest

from app.services import vendor_questionnaire as vq


def good(**over):
    f = {"name": "  Vera   Vendor ", "email": " Vera@Vendor.TEST "}
    for k in vq.KEYS:
        f[f"q_{k}"] = "yes"
    f.update(over)
    return f


def test_a_complete_form_is_accepted_and_tidied():
    parsed, problem = vq.validate(good(d_mfa="  all   staff ", q_breach_history="no", q_location="na"))
    assert problem is None and parsed is not None
    assert parsed["name"] == "Vera Vendor" and parsed["email"] == "vera@vendor.test"
    by = {a["key"]: a for a in parsed["answers"]}
    assert len(parsed["answers"]) == len(vq.QUESTIONS) and by["mfa"]["details"] == "all staff" and by["breach_history"]["answer"] == "no" and by["location"]["answer"] == "na"
    assert by["mfa"]["question"] == dict(vq.QUESTIONS)["mfa"]


def test_every_question_must_be_answered_with_a_known_choice_and_who_answered_is_required():
    parsed, problem = vq.validate(good(q_backup=""))
    assert parsed is None and dict(vq.QUESTIONS)["backup"] in problem
    assert vq.validate(good(q_mfa="maybe"))[0] is None
    assert vq.validate(good(name=""))[0] is None
    assert vq.validate(good(email="not-an-address"))[0] is None
    assert vq.validate(good(email="a b@c.d"))[0] is None


def test_details_are_capped():
    parsed, _ = vq.validate(good(d_mfa="x" * 5000))
    assert len(parsed["answers"][0]["details"]) == vq.MAX_DETAIL


def test_the_form_lists_every_question_with_three_choices_and_escapes_names():
    page = vq.render_form("Acme <b>", "Vendor <script>x</script>", "2026-12-21")
    assert "<script>x" not in page and "<b>" not in page and "&lt;script&gt;" in page
    for key, question in vq.QUESTIONS:
        assert f'name="q_{key}"' in page and f'name="d_{key}"' in page
    assert page.count('value="yes"') == len(vq.QUESTIONS) and page.count('value="na"') == len(vq.QUESTIONS)
    assert 'method="post"' in page and "noindex" in page


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")


class _Req:
    def __init__(self, body: bytes) -> None:
        self._b = body

    async def body(self) -> bytes:
        return self._b


def _form(**over) -> bytes:
    from urllib.parse import urlencode

    return urlencode(good(**over)).encode()


@pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_a_questionnaire_link_is_answered_once_expires_and_can_be_cancelled(monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.api.v1.endpoints import public_pages as pp
    from app.api.v1.endpoints import vendor_management as vm
    from app.db.rls import set_rls_context

    tid, vendor, tag = uuid.uuid4(), uuid.uuid4(), uuid.uuid4().hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app_engine = create_async_engine(APP_URL, poolclass=NullPool)
    monkeypatch.setattr(pp, "AsyncSessionLocal", async_sessionmaker(app_engine, expire_on_commit=False))
    pp.reset_limits()
    staff = SimpleNamespace(tenant_id=tid, user_id=uuid.uuid4(), email="hal@x.test", role="tenant_admin")
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}, state=SimpleNamespace())

    async def with_db(work):
        async with async_sessionmaker(app_engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out

    try:
        async with owner.begin() as c:
            await c.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"Quest {tag}", "s": f"vq-{tag}"})
            await c.execute(
                text("insert into users (id, tenant_id, email, account_name, username, hashed_password, role, is_active) values (:u,:t,'hal@x.test',:a,'hal','x','tenant_admin',true)"),
                {"u": staff.user_id, "t": tid, "a": f"hal-{tag}"},
            )
            await c.execute(text("insert into vendors (id, tenant_id, name) values (:v,:t,'Acme <Hosting>')"), {"v": vendor, "t": tid})

        made = await with_db(lambda db: vm.send_questionnaire(vendor, vm.QLinkIn(), req, tid, db, staff))
        assert made.state == "open" and made.path.startswith("/api/v1/public/vendor-questionnaire/") and made.url is None and not made.emailed
        token = made.path.rsplit("/", 1)[1]

        page = await pp.public_vendor_questionnaire(token)
        assert page.status_code == 200 and b"Acme &lt;Hosting&gt;" in page.body and b'name="q_mfa"' in page.body

        async with owner.begin() as c:
            stored = (await c.execute(text("select token_hash from vendor_questionnaire_links where tenant_id=:t"), {"t": tid})).scalar_one()
            days = (await c.execute(text("select round(extract(epoch from (expires_at - created_at))/86400) from vendor_questionnaire_links where tenant_id=:t"), {"t": tid})).scalar_one()
        assert stored != token and token not in stored and int(days) == 30

        # an incomplete form saves nothing and leaves the link open
        bad = await pp.public_vendor_questionnaire_answer(token, _Req(_form(q_mfa="")))
        assert bad.status_code == 422
        assert (await pp.public_vendor_questionnaire(token)).status_code == 200

        ok = await pp.public_vendor_questionnaire_answer(token, _Req(_form(q_breach_history="no", d_certification="SOC 2 Type II")))
        assert ok.status_code == 200 and b"received" in ok.body

        listed = await with_db(lambda db: vm.list_questionnaires(vendor, tid, db, staff))
        assert len(listed) == 1 and listed[0].state == "answered" and listed[0].respondent_email == "vera@vendor.test" and listed[0].path is None
        by = {a.question: a for a in listed[0].answers}
        assert by[dict(vq.QUESTIONS)["certification"]].details == "SOC 2 Type II" and by[dict(vq.QUESTIONS)["breach_history"]].answer == "no"

        again = await pp.public_vendor_questionnaire(token)
        assert b"Already answered" in again.body and b'name="q_mfa"' not in again.body
        assert (await pp.public_vendor_questionnaire_answer(token, _Req(_form()))).status_code == 410

        for t in ("short", "not-a-real-token-but-the-right-length-xx"):
            for call in (pp.public_vendor_questionnaire(t), pp.public_vendor_questionnaire_answer(t, _Req(_form()))):
                with pytest.raises(HTTPException) as e:
                    await call
                assert e.value.status_code == 404

        # expiry and cancel
        second = await with_db(lambda db: vm.send_questionnaire(vendor, vm.QLinkIn(expires_days=5), req, tid, db, staff))
        t2 = second.path.rsplit("/", 1)[1]
        async with owner.begin() as c:
            await c.execute(text("update vendor_questionnaire_links set expires_at = now() - interval '1 minute' where id = :i"), {"i": second.id})
        assert (await pp.public_vendor_questionnaire(t2)).status_code == 410
        assert (await pp.public_vendor_questionnaire_answer(t2, _Req(_form()))).status_code == 410
        third = await with_db(lambda db: vm.send_questionnaire(vendor, vm.QLinkIn(), req, tid, db, staff))
        t3 = third.path.rsplit("/", 1)[1]
        await with_db(lambda db: vm.cancel_questionnaire(vendor, third.id, req, tid, db, staff))
        assert (await pp.public_vendor_questionnaire(t3)).status_code == 410

        # the vendor history shows it, and e-mailing is refused with a reason when it cannot work
        async with owner.begin() as c:
            actions = {r[0] for r in (await c.execute(text("select action from vendor_history where vendor_id=:v"), {"v": vendor})).all()}
        assert {"questionnaire_sent", "questionnaire_answered", "questionnaire_cancelled"} <= actions
        with pytest.raises(HTTPException) as e:
            await with_db(lambda db: vm.send_questionnaire(vendor, vm.QLinkIn(send=True), req, tid, db, staff))
        assert e.value.status_code == 422 and "account manager" in e.value.detail
    finally:
        async with owner.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("set local session_replication_role = replica"))
            for table in ("vendor_questionnaire_links", "vendor_history", "vendors", "audit_log", "users"):
                await c.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from tenants where id = :t"), {"t": tid})
        await owner.dispose()
        await app_engine.dispose()
