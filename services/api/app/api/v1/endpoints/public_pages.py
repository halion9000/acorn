"""The pages the internet may read without signing in: GET /public/trust/{token}, an organization's public trust page (see app/services/public_trust.py for the safeguards).

This is the ONLY unauthenticated route that shows an organization's own words, so it answers one 404 for an unknown token, a switched-off link and junk; it is looked up across organizations (the visitor has no
organization), then the page is built inside that one organization's scope; and it is rate limited per token and overall so it cannot be used to hammer the database.
"""

from __future__ import annotations

import time
import uuid
from collections import deque

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import mark_platform
from app.models.tenant import Tenant
from app.models.trust_audit import TrustCenterSettings
from app.services import public_trust

router = APIRouter(prefix="/public", tags=["public"])

_PER_MINUTE = 120
_hits: deque[float] = deque()


def _allowed(now: float) -> bool:
    while _hits and _hits[0] < now - 60:
        _hits.popleft()
    if len(_hits) >= _PER_MINUTE:
        return False
    _hits.append(now)
    return True


def reset_limits() -> None:
    _hits.clear()


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/trust/{token}", response_class=HTMLResponse, summary="An organization's public trust page (no sign-in; off unless the organization switched its link on)")
async def public_trust_page(token: str) -> Response:
    from app.api.v1.endpoints.trust_center import _build  # noqa: PLC0415

    if not public_trust.TOKEN_RE.match(token) or not _allowed(time.monotonic()):
        raise _not_found()
    async with AsyncSessionLocal() as db:
        mark_platform(db)  # the visitor has no organization: find the token's
        row = (
            await db.execute(select(TrustCenterSettings).where(TrustCenterSettings.public_token == token, TrustCenterSettings.public_enabled.is_(True)))
        ).scalar_one_or_none()
        if row is None:
            raise _not_found()
        tenant: uuid.UUID = row.tenant_id
        org = (await db.execute(select(Tenant.name).where(Tenant.id == tenant))).scalar_one_or_none() or "this organization"
        async with acting_as_tenant(db, tenant):
            built = await _build(db, tenant)
    page = public_trust.render(
        str(org),
        {
            "headline": built.headline,
            "about": built.about,
            "contact_email": built.contact_email,
            "documents": [d.model_dump() for d in built.documents],
            "frameworks": [f.model_dump() for f in built.frameworks],
            "policies": [p.model_dump() for p in built.policies],
        },
    )
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
