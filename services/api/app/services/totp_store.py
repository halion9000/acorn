"""Storing and checking a person's authenticator-app setup (the database side of ``app.services.totp``).

Every read and write happens inside the person's OWN tenant scope (``users.tenant_id``), whichever tenant they happen to be viewing, because the row belongs to the person, not to what they are looking at.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.rls_scope import acting_as_tenant
from app.models.user_totp import UserTotp
from app.security.credential_vault import get_vault
from app.services import totp


async def load(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID) -> UserTotp | None:
    async with acting_as_tenant(db, tenant_id):
        return (await db.execute(select(UserTotp).where(UserTotp.user_id == user_id, UserTotp.tenant_id == tenant_id))).scalars().first()


async def is_enabled(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    row = await load(db, user_id, tenant_id)
    return row is not None and row.confirmed_at is not None


async def start_enrolment(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID, account: str) -> tuple[str, str]:
    """Make (or replace) the person's UNCONFIRMED secret and return (secret, otpauth address). Does nothing to signing in until confirmed. Refuses when one is already confirmed (turn it off first)."""
    row = await load(db, user_id, tenant_id)
    if row is not None and row.confirmed_at is not None:
        raise ValueError("An authenticator app is already set up. Turn it off first to set up a new one.")
    secret = totp.new_secret()
    async with acting_as_tenant(db, tenant_id):
        if row is None:
            db.add(UserTotp(user_id=user_id, tenant_id=tenant_id, secret_enc=get_vault().encrypt(secret), recovery_hashes=[]))
        else:
            row.secret_enc = get_vault().encrypt(secret)
            row.last_used_step = None
        await db.flush()
    return secret, totp.otpauth_uri(secret, account)


async def confirm(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID, code: str, now: datetime | None = None) -> list[str] | None:
    """The person typed a code from the app. When it is right the setup is confirmed and the recovery codes are returned (shown once); None when the code is wrong or no setup was started."""
    row = await load(db, user_id, tenant_id)
    if row is None or row.confirmed_at is not None:
        return None
    moment = now or datetime.now(UTC)
    step = totp.verify(get_vault().decrypt(row.secret_enc), code, moment.timestamp())
    if step is None:
        return None
    codes = totp.new_recovery_codes()
    async with acting_as_tenant(db, tenant_id):
        row.confirmed_at = moment
        row.last_used_step = step
        row.recovery_hashes = [totp.hash_recovery(c) for c in codes]
        await db.flush()
    return codes


async def check_code(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID, code: str, now: datetime | None = None) -> str | None:
    """Whether a sign-in code is acceptable: a current authenticator code that has not been used ("code"), or an unspent recovery code ("recovery"). Spends whichever it was. None when it is neither."""
    row = await load(db, user_id, tenant_id)
    if row is None or row.confirmed_at is None:
        return None
    moment = now or datetime.now(UTC)
    step = totp.verify(get_vault().decrypt(row.secret_enc), code, moment.timestamp(), row.last_used_step)
    if step is not None:
        async with acting_as_tenant(db, tenant_id):
            row.last_used_step = step
            await db.flush()
        return "code"
    left = totp.use_recovery(list(row.recovery_hashes or []), code)
    if left is not None:
        async with acting_as_tenant(db, tenant_id):
            row.recovery_hashes = left
            await db.flush()
        return "recovery"
    return None


async def remove(db: Any, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    row = await load(db, user_id, tenant_id)
    if row is None:
        return False
    async with acting_as_tenant(db, tenant_id):
        await db.delete(row)
        await db.flush()
    return True
