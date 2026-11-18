"""Where the weekly compliance notice goes: an e-mail list and an optional web address (Compliance, Notices).

Read with ``reports:read``, changed with ``reports:write``. The same list the Compliance page shows is sent at most once a week and only when something is waiting; ``/send`` sends it now (to test the setup).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.governance import ComplianceNotice
from app.services import compliance_notice as cn
from app.services.audit import emit_audit
from app.services.compliance_notice_sender import send_notice

router = APIRouter(prefix="/compliance/notices", tags=["compliance"])


class NoticeOut(BaseModel):
    emails: list[str]
    webhook_url: str | None
    weekly: bool
    last_sent_at: datetime | None
    last_result: str | None


class NoticeIn(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=60)
    webhook_url: str | None = Field(default=None, max_length=600)
    weekly: bool = False


class SendOut(BaseModel):
    sent: bool
    items: int
    email: str
    webhook: str


def _out(n: ComplianceNotice | None) -> NoticeOut:
    if n is None:
        return NoticeOut(emails=[], webhook_url=None, weekly=False, last_sent_at=None, last_result=None)
    return NoticeOut(emails=list(n.emails or []), webhook_url=n.webhook_url, weekly=n.weekly, last_sent_at=n.last_sent_at, last_result=n.last_result)


async def _row(db: DBSession, tenant: object) -> ComplianceNotice | None:
    return (await db.execute(select(ComplianceNotice).where(ComplianceNotice.tenant_id == tenant))).scalar_one_or_none()


@router.get("", response_model=NoticeOut, dependencies=[Depends(require_permission("reports:read"))])
async def get_notice(tenant: ScopeTenant, db: DBSession) -> NoticeOut:
    return _out(await _row(db, tenant))


@router.put("", response_model=NoticeOut)
async def save_notice(
    tenant: ScopeTenant, body: NoticeIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> NoticeOut:
    emails = cn.clean_emails(body.emails)
    url = (body.webhook_url or "").strip() or None
    problem = cn.webhook_problem(url)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    if body.weekly and not emails and not url:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give at least one e-mail address or a web address to send the weekly notice to.")
    row = await _row(db, tenant)
    who = (getattr(user, "email", None) or None)
    if row is None:
        row = ComplianceNotice(tenant_id=tenant, emails=emails, webhook_url=url, weekly=body.weekly, updated_by=who)
        db.add(row)
    else:
        row.emails, row.webhook_url, row.weekly, row.updated_by = emails, url, body.weekly, who
        row.updated_at = datetime.now(UTC)
    await db.flush()
    await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action="compliance_notice:saved", resource="compliance_notice", resource_id=str(tenant), changes={"emails": len(emails), "webhook": bool(url), "weekly": body.weekly}, request=request)
    await db.commit()
    return _out(row)


@router.post("/send", response_model=SendOut)
async def send_now(
    tenant: ScopeTenant, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> SendOut:
    """Send the notice now, whether or not a week has passed, to the people and the web address saved here."""
    row = await _row(db, tenant)
    if row is None or (not row.emails and not row.webhook_url):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Save an e-mail address or a web address first.")
    out = await send_notice(db, row)
    await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action="compliance_notice:sent", resource="compliance_notice", resource_id=str(tenant), changes={"items": out["items"], "sent": out["sent"]}, request=request)
    await db.commit()
    return SendOut(sent=out["sent"], items=out["items"], email=out["email"], webhook=out["webhook"])
