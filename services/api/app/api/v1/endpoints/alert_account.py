"""What Microsoft 365 knows about the person an alert names: GET /api/v1/alerts/{alert_id}/account.

An alert from any tool (a Huntress incident, a Petra detection, a Blumira finding) often names a person. Without leaving the alert, the analyst sees that person's last seven days of Microsoft 365 sign-ins
(from what CORE already reads through CIPP and A.C.O.R.N stores), how many failed, from which countries and apps, whether any was flagged risky, and their directory and multi-factor facts. Nothing is fetched from
Microsoft when the page opens, so it costs nothing and cannot be abused to probe a tenant; a person Microsoft 365 does not hold gets "no Microsoft 365 account found", never a guess.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, require_permission
from app.api.v1.endpoints.alert_related import names_of
from app.db.rls import TenantDBSession
from app.models.alert import Alert
from app.models.signin import IdentityMfaUser, SigninEvent
from app.services.alert_scope import alert_scope

router = APIRouter(prefix="/alerts", tags=["alerts"])

WINDOW_DAYS = 7
MAX_PEOPLE = 3
RECENT = 8
RISKY = {"low", "medium", "high"}


class SigninRow(BaseModel):
    at: datetime
    country: str | None = None
    city: str | None = None
    app: str | None = None
    ip: str | None = None
    success: bool
    mfa: bool | None = None
    risk: str | None = None


class AccountFacts(BaseModel):
    enabled: bool
    admin: bool
    licensed: bool
    mfa_registered: bool
    methods: str | None = None
    conditional_access: bool
    per_user_mfa: str | None = None


class PersonContext(BaseModel):
    user: str
    found: bool
    account: AccountFacts | None = None
    signins: int = 0
    failed: int = 0
    without_mfa: int = 0
    risky: int = 0
    countries: list[tuple[str, int]] = []
    apps: list[tuple[str, int]] = []
    last_success: datetime | None = None
    recent: list[SigninRow] = []
    note: str | None = None


class AccountContext(BaseModel):
    window_days: int = WINDOW_DAYS
    people: list[PersonContext]


def emails_of(users: Any) -> list[str]:
    """The names in the alert that are e-mail addresses (lower case, once each), at most MAX_PEOPLE: only those can be looked up in Microsoft 365."""
    seen: list[str] = []
    for name in names_of(users):
        low = name.lower()
        if "@" in low and " " not in low and low not in seen:
            seen.append(low)
    return seen[:MAX_PEOPLE]


def summarise(user: str, rows: list[Any]) -> PersonContext:
    """The sign-in picture of one person from their sign-in rows, newest first (pure). ``risky`` counts sign-ins Microsoft rated low, medium or high; ``without_mfa`` successful interactive ones with no second factor."""
    ok = [r for r in rows if r.success]
    countries = Counter((r.country or "unknown") for r in rows)
    apps = Counter((r.app or "unknown") for r in rows)
    return PersonContext(
        user=user,
        found=True,
        signins=len(rows),
        failed=sum(1 for r in rows if not r.success),
        without_mfa=sum(1 for r in ok if r.interactive and r.mfa is False),
        risky=sum(1 for r in rows if str(r.risk or "").lower() in RISKY),
        countries=countries.most_common(5),
        apps=apps.most_common(5),
        last_success=max((r.occurred_at for r in ok), default=None),
        recent=[
            SigninRow(
                at=r.occurred_at, country=r.country, city=r.city, app=r.app, ip=r.ip_address, success=r.success, mfa=r.mfa, risk=r.risk
            )
            for r in rows[:RECENT]
        ],
    )


@router.get(
    "/{alert_id}/account", response_model=AccountContext, summary="Microsoft 365 sign-ins and account facts for the people an alert names"
)
async def alert_account(
    alert_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: TenantDBSession,
) -> AccountContext:
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        people: list[PersonContext] = []
        since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
        for email in emails_of(alert.affected_users):
            account = (
                await db.execute(
                    select(IdentityMfaUser).where(IdentityMfaUser.tenant_id == tid, func.lower(IdentityMfaUser.upn) == email).limit(1)
                )
            ).scalar_one_or_none()
            rows = (
                (
                    await db.execute(
                        select(SigninEvent)
                        .where(
                            SigninEvent.tenant_id == tid, func.lower(SigninEvent.user_principal) == email, SigninEvent.occurred_at >= since
                        )
                        .order_by(SigninEvent.occurred_at.desc())
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
            if account is None and not rows:
                people.append(
                    PersonContext(user=email, found=False, note="No Microsoft 365 account or recent sign-in found for this address.")
                )
                continue
            p = summarise(email, list(rows))
            if account is not None:
                p.account = AccountFacts(
                    enabled=account.enabled,
                    admin=account.admin,
                    licensed=account.licensed,
                    mfa_registered=account.registered,
                    methods=account.methods or None,
                    conditional_access=account.ca_enforced,
                    per_user_mfa=account.per_user,
                )
            if not rows:
                p.note = f"No sign-ins recorded in the last {WINDOW_DAYS} days."
            people.append(p)
        return AccountContext(people=people)
