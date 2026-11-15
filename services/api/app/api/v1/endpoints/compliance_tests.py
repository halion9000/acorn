"""Automated control tests (Secureframe parity plan, the tests engine): see how the client's own checks answer each security practice, and record the answers as evidence for the controls.

Read with ``reports:read`` (the results are worked out live from the checks A.C.O.R.N holds, nothing is stored by reading). Recording writes evidence (``reports:write``): it replaces only the records an earlier recording made,
and only for the frameworks that are turned on. ``client_id`` reads or writes one of the caller's clients as the other compliance routes do. See ``services/compliance_tests.py`` for what each result means.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.models.signin import ClientM365Check
from app.services import compliance_tests as engine

router = APIRouter(prefix="/compliance/tests", tags=["compliance"])


class ControlRef(BaseModel):
    framework: str
    control_id: str
    on: bool  # the framework is turned on, so a recording writes evidence for it


class CheckSeen(BaseModel):
    key: str
    status: str


class TestResult(BaseModel):
    id: str
    title: str
    why: str
    state: str  # pass, fail, partly or not_tested
    met: int
    total: int
    checks: list[CheckSeen]
    controls: list[ControlRef]


class TestsOut(BaseModel):
    results: list[TestResult]
    counts: dict[str, int]
    enabled: list[str]
    checks_held: int  # how many checks the client has in all (0: nothing has been read for it yet)


class RecordOut(BaseModel):
    written: int
    replaced: int
    results: TestsOut


async def _checks(db: DBSession, tenant: object) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in (await db.execute(select(ClientM365Check).where(ClientM365Check.tenant_id == tenant))).scalars():
        for c in row.checks or []:
            if isinstance(c, dict) and isinstance(c.get("key"), str) and c.get("status") in ("met", "partly", "not_met"):
                out[c["key"]] = c["status"]
    return out


async def _enabled(db: DBSession, tenant: object) -> list[str]:
    return sorted(
        (await db.execute(select(ComplianceEnabledFramework.framework).where(ComplianceEnabledFramework.tenant_id == tenant))).scalars()
    )


def _out(results: list[dict], enabled: list[str], held: int) -> TestsOut:
    on = set(enabled)
    counts = dict.fromkeys((engine.PASS, engine.FAIL, engine.PARTLY, engine.NOT_TESTED), 0)
    shown = []
    for r in results:
        t: engine.ControlTest = r["test"]
        counts[r["state"]] += 1
        shown.append(
            TestResult(
                id=t.id,
                title=t.title,
                why=t.why,
                state=r["state"],
                met=r["met"],
                total=r["total"],
                checks=[CheckSeen(key=k, status=s) for k, s in r["seen"].items()],
                controls=[ControlRef(framework=f, control_id=c, on=f in on) for f, c in t.controls],
            )
        )
    return TestsOut(results=shown, counts=counts, enabled=enabled, checks_held=held)


@router.get("", response_model=TestsOut, summary="How the client's checks answer each security practice, worked out now")
async def list_tests(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> TestsOut:
    checks = await _checks(db, tenant)
    return _out(engine.evaluate_all(checks), await _enabled(db, tenant), len(checks))


@router.post("/record", response_model=RecordOut, summary="Write the results as evidence for the controls of the frameworks that are on")
async def record_tests(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> RecordOut:
    checks = await _checks(db, tenant)
    enabled = await _enabled(db, tenant)
    results = engine.evaluate_all(checks)
    done = await engine.record(db, tenant, engine.evidence_rows(results, set(enabled)), datetime.now(UTC))
    await db.commit()
    return RecordOut(**done, results=_out(results, enabled, len(checks)))
