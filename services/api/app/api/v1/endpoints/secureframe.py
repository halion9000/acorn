"""Secureframe's compliance state, shown read only on the Compliance page.

CORE reads Secureframe (control tests, frameworks, risks and policies) with the customer's own API key and sends ``POST /core-feed/{token}/secureframe``: the test counts, the failing and passing tests per
framework, the oldest failing tests with their owner, and the number of risks and policies. No credential, policy text or evidence is in it. ``GET /secureframe`` shows the latest report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_sessions import adopt_tenant
from app.models.secureframe_report import SecureframeReport

router = APIRouter(prefix="/secureframe", tags=["secureframe"])
ingest_router = APIRouter(prefix="/inbox", tags=["secureframe"])

MAX_FAILING = 100
MAX_FRAMEWORKS = 60
_COUNT = Field(ge=0, le=10_000_000)


class TestCounts(BaseModel):
    total: int = _COUNT
    enabled: int = _COUNT
    passing: int = _COUNT
    failing: int = _COUNT
    not_evaluated: int = _COUNT
    disabled: int = _COUNT


class FrameworkCounts(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=120)
    failing: int = _COUNT
    passing: int = _COUNT


class FailingTest(BaseModel):
    key: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    owner: str | None = Field(default=None, max_length=120)
    failing_since: datetime | None = None
    frameworks: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=40)
    domain: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=300)


class SecureframeBody(BaseModel):
    tests: TestCounts
    frameworks: list[FrameworkCounts] = Field(default_factory=list, max_length=MAX_FRAMEWORKS)
    failing: list[FailingTest] = Field(default_factory=list, max_length=MAX_FAILING)
    # None: the key's role may not read that list, so the number is not known (not zero).
    risks: int | None = Field(default=None, ge=0, le=10_000_000)
    policies: int | None = Field(default=None, ge=0, le=10_000_000)


class ReportIn(BaseModel):
    vendor: str = Field(default="secureframe", pattern="^secureframe$")
    report: SecureframeBody


class ReportResponse(BaseModel):
    stored: bool = True


class SecureframeView(BaseModel):
    """What the Compliance page shows. ``report`` is None until CORE has sent one (Secureframe not connected, or not read yet)."""

    report: SecureframeBody | None
    received_at: datetime | None
    # enabled tests that pass, as a percentage of the enabled tests that were evaluated; None when none were.
    passing_percent: float | None = None


def passing_percent(tests: TestCounts) -> float | None:
    evaluated = tests.passing + tests.failing
    return round(100 * tests.passing / evaluated, 1) if evaluated else None


@ingest_router.post("/core-feed/{tenant_token}/secureframe", response_model=ReportResponse)
async def report_core_feed_secureframe(tenant_token: str, body: ReportIn, db: DBSession) -> ReportResponse:
    """Keep CORE's latest Secureframe report (replacing the one before)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    values = {"tenant_id": owner, "report": body.report.model_dump(mode="json")}
    stmt = pg_insert(SecureframeReport).values(values)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["tenant_id"], set_={"report": stmt.excluded.report, "received_at": func.now()})
    )
    await db.commit()
    return ReportResponse()


@router.get("", response_model=SecureframeView, summary="Secureframe's control tests: how many pass, which fail and who owns them")
async def secureframe_view(user: Annotated[AuthUser, Depends(require_permission("reports:read"))], db: DBSession) -> SecureframeView:
    row = (await db.execute(select(SecureframeReport).where(SecureframeReport.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return SecureframeView(report=None, received_at=None)
    report = SecureframeBody.model_validate(row.report)
    return SecureframeView(report=report, received_at=row.received_at, passing_percent=passing_percent(report.tests))
