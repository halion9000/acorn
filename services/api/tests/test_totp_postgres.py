"""Authenticator-app setup against a REAL Postgres as the restricted application role (row-level security on): it works inside the person's own tenant and is invisible from any other.

Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid

import pytest
from app.db.rls_scope import acting_as_tenant
from app.services import totp, totp_store
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")]


async def test_setup_confirm_and_sign_in_work_in_the_persons_tenant_and_are_invisible_from_another():
    tag = uuid.uuid4().hex[:8]
    ta, tb, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for t in (ta, tb):
                await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": t, "n": f"t-{tag}-{str(t)[:4]}", "s": f"t-{tag}-{str(t)[:4]}"})
            await conn.execute(
                text("insert into users (id, tenant_id, email, username, account_name, hashed_password, role, is_active) values (:i, :t, :e, 'u', :a, 'x', 'admin', true)"),
                {"i": uid, "t": ta, "e": f"u-{tag}@x.example", "a": f"u{tag}"},
            )
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            secret, uri = await totp_store.start_enrolment(db, uid, ta, "u@x.example")
            await db.commit()
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            codes = await totp_store.confirm(db, uid, ta, totp.code_for_step(secret, totp.current_step()))
            await db.commit()
            assert codes is not None and len(codes) == 10
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            assert await totp_store.is_enabled(db, uid, ta) is True
            assert await totp_store.check_code(db, uid, ta, codes[0]) == "recovery"
            await db.commit()
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            assert await totp_store.check_code(db, uid, ta, codes[0]) is None, "a spent recovery code stays spent"
            async with acting_as_tenant(db, tb):
                from app.models.user_totp import UserTotp
                from sqlalchemy import select

                seen = (await db.execute(select(UserTotp))).scalars().all()
            assert seen == [], "another tenant cannot see the row"
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            stored = (await conn.execute(text("select secret_enc from user_totp where user_id = :u"), {"u": uid})).scalar_one()
            assert stored != secret
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from user_totp where user_id = :u"), {"u": uid})
            await conn.execute(text("delete from users where id = :u"), {"u": uid})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(ta), str(tb)]})
        await owner.dispose()
        await app.dispose()
