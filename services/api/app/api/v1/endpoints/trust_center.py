"""The trust center (Secureframe parity plan): what an organization shows its own customers about its security, behind sign-in for now.

A person with write access chooses a headline, an about text, a contact address, which of the frameworks that are on to show, which policies to list and which documents to link. The page shows the control health of each
chosen framework as it is when the page is read (never a number typed in), the chosen policies by name with when each was last reviewed, and the documents. A public share link and a sign-in for auditors are not built:
this is read by people who sign in. Read with ``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.api.v1.endpoints.compliance_controls import build_rows, evidence_by_control
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.models.governance import GovernanceItem
from app.models.trust_audit import TrustCenterSettings
from app.services import compliance_audit as audit
from app.services import compliance_health, public_trust

router = APIRouter(prefix="/compliance/trust-center", tags=["compliance"])

MAX_DOCS = 30


class DocumentIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    url: str = Field(min_length=8, max_length=1000)


class SettingsIn(BaseModel):
    enabled: bool = False
    headline: str = Field(default="", max_length=200)
    about: str = Field(default="", max_length=5000)
    contact_email: str | None = Field(default=None, max_length=320)
    frameworks: list[Annotated[str, Field(max_length=20)]] = Field(default_factory=list, max_length=12)
    policy_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    documents: list[DocumentIn] = Field(default_factory=list, max_length=MAX_DOCS)


class FrameworkLine(BaseModel):
    framework: str
    controls: int
    healthy: int
    percent_healthy: int | None


class PolicyLine(BaseModel):
    id: uuid.UUID
    title: str
    last_reviewed_at: date | None


class PolicyChoice(BaseModel):
    id: uuid.UUID
    title: str


class TrustCenterOut(BaseModel):
    enabled: bool
    headline: str
    about: str
    contact_email: str | None
    documents: list[DocumentIn]
    frameworks: list[FrameworkLine]  # the chosen frameworks, with their health as it is now
    policies: list[PolicyLine]
    updated_at: datetime | None
    updated_by: str | None
    # What can be chosen (for the person editing).
    available_frameworks: list[str]
    available_policies: list[PolicyChoice]
    chosen_frameworks: list[str]
    chosen_policy_ids: list[uuid.UUID]
    # The public share link: whether it is on, and its path (add the public address of A.C.O.R.N in front). None until it was switched on once.
    public_enabled: bool = False
    public_path: str | None = None


def clean_documents(docs: list[DocumentIn]) -> list[dict[str, str]]:
    """The documents kept: a link must be https (or http); anything else is refused (pure)."""
    out = []
    for d in docs:
        url = d.url.strip()
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError(f"The link for {d.name} must start with https://")
        out.append({"name": d.name.strip(), "url": url})
    return out


def framework_lines(chosen: list[str], rows_by_fw: dict[str, list[str]]) -> list[FrameworkLine]:
    """One line per chosen framework from the state of each of its controls (pure)."""
    out = []
    for fw in chosen:
        states = rows_by_fw.get(fw, [])
        counts = dict.fromkeys(compliance_health.STATES, 0)
        for s in states:
            counts[s] += 1
        out.append(
            FrameworkLine(
                framework=fw, controls=len(states), healthy=counts["healthy"], percent_healthy=compliance_health.percent_healthy(counts)
            )
        )
    return out


async def _build(db: DBSession, tenant: uuid.UUID) -> TrustCenterOut:
    row = (await db.execute(select(TrustCenterSettings).where(TrustCenterSettings.tenant_id == tenant))).scalar_one_or_none()
    enabled_fw = sorted(
        (await db.execute(select(ComplianceEnabledFramework.framework).where(ComplianceEnabledFramework.tenant_id == tenant))).scalars()
    )
    policies = (
        (
            await db.execute(
                select(GovernanceItem)
                .where(GovernanceItem.tenant_id == tenant, GovernanceItem.kind == "policy", GovernanceItem.archived_at.is_(None))
                .order_by(GovernanceItem.title)
            )
        )
        .scalars()
        .all()
    )
    chosen_fw = [f for f in (row.frameworks if row else []) if f in FRAMEWORKS and f in enabled_fw]
    chosen_ids = {uuid.UUID(str(p)) for p in (row.policy_ids if row else [])}
    evidence = await evidence_by_control(db, tenant, chosen_fw)
    now = datetime.now(UTC)
    states = {fw: [r.state for r in build_rows([fw], evidence, now)] for fw in chosen_fw}
    return TrustCenterOut(
        enabled=bool(row and row.enabled),
        headline=row.headline if row else "",
        about=row.about if row else "",
        contact_email=row.contact_email if row else None,
        documents=[DocumentIn(**d) for d in (row.documents if row else [])],
        frameworks=framework_lines(chosen_fw, states),
        policies=[PolicyLine(id=p.id, title=p.title, last_reviewed_at=p.last_reviewed_at) for p in policies if p.id in chosen_ids],
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
        available_frameworks=enabled_fw,
        available_policies=[PolicyChoice(id=p.id, title=p.title) for p in policies],
        chosen_frameworks=chosen_fw,
        chosen_policy_ids=sorted(chosen_ids, key=str),
        public_enabled=bool(row and row.public_enabled and row.public_token),
        public_path=public_trust.link_path(row.public_token if row else None),
    )


@router.get("", response_model=TrustCenterOut, summary="The trust center as it is shown, and what can be chosen for it")
async def get_trust_center(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> TrustCenterOut:
    return await _build(db, tenant)


@router.put("", response_model=TrustCenterOut, summary="Choose what the trust center shows")
async def put_trust_center(
    body: SettingsIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> TrustCenterOut:
    try:
        docs = clean_documents(body.documents)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    bad = [f for f in body.frameworks if f not in FRAMEWORKS]
    if bad:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{bad[0]} is not a framework.")
    policy_rows = await db.execute(
        select(GovernanceItem.id).where(
            GovernanceItem.tenant_id == tenant, GovernanceItem.kind == "policy", GovernanceItem.archived_at.is_(None)
        )
    )
    mine = set(policy_rows.scalars())
    stray = [p for p in body.policy_ids if p not in mine]
    if stray:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One of the policies is not in your library.")
    row = (await db.execute(select(TrustCenterSettings).where(TrustCenterSettings.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        row = TrustCenterSettings(tenant_id=tenant)
        db.add(row)
    row.enabled = body.enabled
    row.headline = body.headline.strip()
    row.about = body.about.strip()
    row.contact_email = (body.contact_email or "").strip() or None
    row.frameworks = sorted(set(body.frameworks))
    row.policy_ids = [str(p) for p in dict.fromkeys(body.policy_ids)]
    row.documents = docs
    row.updated_by = getattr(user, "email", None)
    row.updated_at = datetime.now(UTC)
    await audit.note(
        db,
        tenant,
        user,
        "trust_center:changed",
        "trust_center",
        tenant,
        enabled=row.enabled,
        frameworks=row.frameworks,
        policies=len(row.policy_ids),
        documents=len(row.documents),
    )
    await db.commit()
    return await _build(db, tenant)


class PublicLinkIn(BaseModel):
    enabled: bool
    # True makes a new link: the old one stops working at once (use it when a link was shared too widely).
    new_link: bool = False


@router.put("/public", response_model=TrustCenterOut, summary="Switch the public share link of the trust center on or off, or make a new link")
async def put_public_link(
    body: PublicLinkIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> TrustCenterOut:
    """Off by default. Switching on makes the link the first time; switching off keeps the link but it answers 404 until it is on again; ``new_link`` replaces it. Written to the audit log."""
    row = (await db.execute(select(TrustCenterSettings).where(TrustCenterSettings.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        row = TrustCenterSettings(tenant_id=tenant)
        db.add(row)
    if body.enabled and (row.public_token is None or body.new_link):
        row.public_token = public_trust.new_token()
    row.public_enabled = body.enabled and row.public_token is not None
    row.updated_by = getattr(user, "email", None)
    row.updated_at = datetime.now(UTC)
    await audit.note(db, tenant, user, "trust_center:public_link", "trust_center", tenant, enabled=row.public_enabled, new_link=body.new_link)
    await db.commit()
    return await _build(db, tenant)
