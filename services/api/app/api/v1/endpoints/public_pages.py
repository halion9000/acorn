"""The pages the internet may read without signing in: GET /public/trust/{token}, an organization's public trust page (see app/services/public_trust.py for the safeguards).

This is the ONLY unauthenticated route that shows an organization's own words, so it answers one 404 for an unknown token, a switched-off link and junk; it is looked up across organizations (the visitor has no
organization), then the page is built inside that one organization's scope; and it is rate limited per token and overall so it cannot be used to hammer the database.
"""

from __future__ import annotations

import time
import uuid
from collections import deque

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, update

from app.db.database import AsyncSessionLocal
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import mark_platform
from app.models.governance import GovernanceItem, GovernanceVersion
from app.models.vendor_management import Vendor, VendorHistory, VendorQuestionnaireLink
from app.models.policy_acceptance import PolicyAcceptance, PolicyAcceptLink
from app.models.tenant import Tenant
from app.models.trust_audit import TrustCenterSettings
from app.services import policy_links, public_trust, vendor_questionnaire

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


_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _page(html_text: str, code: int = 200) -> HTMLResponse:
    return HTMLResponse(html_text, status_code=code, headers=_PAGE_HEADERS)


async def _open_link(db, token: str):  # noqa: ANN001
    """The link row for a well-formed token, or None. Looked up by hash across organizations (the visitor has no sign-in)."""
    mark_platform(db)
    return (await db.execute(select(PolicyAcceptLink).where(PolicyAcceptLink.token_hash == policy_links.hash_token(token)))).scalar_one_or_none()


@router.get("/policy/{token}", response_class=HTMLResponse, summary="A one-time page to read and accept a policy (no sign-in; the link is made by staff, works once and expires)")
async def public_policy_page(token: str) -> Response:
    if not policy_links.TOKEN_RE.match(token) or not _allowed(time.monotonic()):
        raise _not_found()
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        link = await _open_link(db, token)
        if link is None:
            raise _not_found()
        state = policy_links.state_of(link.expires_at, link.used_at, now)
        if state == "used":
            return _page(policy_links.render_message("Already accepted", "This policy was accepted with this link. Nothing more is needed."))
        if state == "expired":
            return _page(policy_links.render_message("This link has expired", "Ask the person who sent it for a new one."), 410)
        tenant: uuid.UUID = link.tenant_id
        org = (await db.execute(select(Tenant.name).where(Tenant.id == tenant))).scalar_one_or_none() or "this organization"
        async with acting_as_tenant(db, tenant):
            title = (await db.execute(select(GovernanceItem.title).where(GovernanceItem.id == link.item_id))).scalar_one_or_none()
            text = (
                await db.execute(select(GovernanceVersion.body).where(GovernanceVersion.item_id == link.item_id, GovernanceVersion.version == link.version))
            ).scalar_one_or_none()
        if title is None or text is None:
            raise _not_found()
        return _page(policy_links.render_form(str(org), str(title), link.version, str(text), link.email, link.expires_at.date().isoformat()))


@router.post("/policy/{token}", response_class=HTMLResponse, summary="Accept the policy on a one-time link (records the acceptance; the link cannot be used again)")
async def public_policy_accept(token: str, request: Request) -> Response:
    if not policy_links.TOKEN_RE.match(token) or not _allowed(time.monotonic()):
        raise _not_found()
    fields = policy_links.parse_form(await request.body())
    name = " ".join(fields.get("name", "").split())[:120]
    if fields.get("agree") != "yes" or not name:
        return _page(policy_links.render_message("Not accepted", "Type your full name and tick the box to accept. Go back and try again."), 422)
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        link = await _open_link(db, token)
        if link is None:
            raise _not_found()
        if policy_links.state_of(link.expires_at, link.used_at, now) != "open":
            return _page(policy_links.render_message("This link cannot be used", "It was already used or it has expired."), 410)
        tenant: uuid.UUID = link.tenant_id
        async with acting_as_tenant(db, tenant):
            # claim the link first, in one statement, so two clicks at once record one acceptance
            claimed = (
                await db.execute(
                    update(PolicyAcceptLink)
                    .where(PolicyAcceptLink.id == link.id, PolicyAcceptLink.used_at.is_(None))
                    .values(used_at=now)
                    .returning(PolicyAcceptLink.id)
                )
            ).first()
            if claimed is None:
                return _page(policy_links.render_message("This link cannot be used", "It was already used."), 410)
            exists = (
                await db.execute(
                    select(func.count()).select_from(PolicyAcceptance).where(
                        PolicyAcceptance.item_id == link.item_id, PolicyAcceptance.version == link.version, PolicyAcceptance.email == link.email
                    )
                )
            ).scalar_one()
            if not exists:
                db.add(
                    PolicyAcceptance(
                        id=uuid.uuid4(), tenant_id=tenant, item_id=link.item_id, version=link.version, email=link.email,
                        display_name=name, accepted_on=date.today(), recorded_by="link",
                    )
                )
            await db.commit()
    return _page(policy_links.render_message("Thank you", "Your acceptance was recorded."))


@router.get("/vendor-questionnaire/{token}", response_class=HTMLResponse, summary="A one-time security questionnaire for a vendor (no sign-in; the link is made by staff, works once and expires)")
async def public_vendor_questionnaire(token: str) -> Response:
    if not policy_links.TOKEN_RE.match(token) or not _allowed(time.monotonic()):
        raise _not_found()
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        mark_platform(db)
        link = (await db.execute(select(VendorQuestionnaireLink).where(VendorQuestionnaireLink.token_hash == policy_links.hash_token(token)))).scalar_one_or_none()
        if link is None:
            raise _not_found()
        state = policy_links.state_of(link.expires_at, link.submitted_at, now)
        if state == "used":
            return _page(policy_links.render_message("Already answered", "The answers for this questionnaire were received. Nothing more is needed."))
        if state == "expired":
            return _page(policy_links.render_message("This link has expired", "Ask the person who sent it for a new one."), 410)
        tenant: uuid.UUID = link.tenant_id
        org = (await db.execute(select(Tenant.name).where(Tenant.id == tenant))).scalar_one_or_none() or "this organization"
        async with acting_as_tenant(db, tenant):
            vendor = (await db.execute(select(Vendor.name).where(Vendor.id == link.vendor_id))).scalar_one_or_none()
        if vendor is None:
            raise _not_found()
        return _page(vendor_questionnaire.render_form(str(org), str(vendor), link.expires_at.date().isoformat()))


@router.post("/vendor-questionnaire/{token}", response_class=HTMLResponse, summary="Send the answers on a one-time questionnaire link (saved once; the link cannot be used again)")
async def public_vendor_questionnaire_answer(token: str, request: Request) -> Response:
    if not policy_links.TOKEN_RE.match(token) or not _allowed(time.monotonic()):
        raise _not_found()
    raw = await request.body()
    parsed, problem = vendor_questionnaire.validate(policy_links.parse_form(raw, limit=64_000))
    if parsed is None:
        return _page(policy_links.render_message("Not sent", f"{problem} Go back and try again."), 422)
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        mark_platform(db)
        link = (await db.execute(select(VendorQuestionnaireLink).where(VendorQuestionnaireLink.token_hash == policy_links.hash_token(token)))).scalar_one_or_none()
        if link is None:
            raise _not_found()
        if policy_links.state_of(link.expires_at, link.submitted_at, now) != "open":
            return _page(policy_links.render_message("This link cannot be used", "It was already answered or it has expired."), 410)
        tenant: uuid.UUID = link.tenant_id
        async with acting_as_tenant(db, tenant):
            claimed = (
                await db.execute(
                    update(VendorQuestionnaireLink)
                    .where(VendorQuestionnaireLink.id == link.id, VendorQuestionnaireLink.submitted_at.is_(None))
                    .values(submitted_at=now, respondent_name=parsed["name"], respondent_email=parsed["email"], answers=parsed["answers"])
                    .returning(VendorQuestionnaireLink.id)
                )
            ).first()
            if claimed is None:
                return _page(policy_links.render_message("This link cannot be used", "It was already answered."), 410)
            db.add(VendorHistory(id=uuid.uuid4(), tenant_id=tenant, vendor_id=link.vendor_id, actor=parsed["email"], action="questionnaire_answered", detail=f"answered by {parsed['name']}"))
            await db.commit()
    return _page(policy_links.render_message("Thank you", "Your answers were received."))
