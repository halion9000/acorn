"""Automated control tests (Secureframe parity plan, the tests engine): see how the client's own checks answer each security practice, and record the answers as evidence for the controls.

Read with ``reports:read`` (the results are worked out live from the checks A.C.O.R.N holds, nothing is stored by reading). Recording writes evidence (``reports:write``): it replaces only the records an earlier recording made,
and only for the frameworks that are turned on. ``client_id`` reads or writes one of the caller's clients as the other compliance routes do. See ``services/compliance_tests.py`` for what each result means.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.models.governance import ComplianceTestSchedule
from app.models.signin import ClientM365Check
from app.models.tenant import Tenant
from app.services import compliance_audit as audit
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
    enabled: bool = True  # False when the client turned this test off in the library
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


async def _disabled(db: DBSession, tenant: object) -> frozenset[str]:
    row = await db.get(Tenant, tenant)
    return engine.disabled_of(row.settings if row else None)


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
        if r.get("enabled", True):
            counts[r["state"]] += 1
        shown.append(
            TestResult(
                enabled=bool(r.get("enabled", True)),
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
    return _out(engine.evaluate_all(checks, await _disabled(db, tenant)), await _enabled(db, tenant), len(checks))


@router.post("/record", response_model=RecordOut, summary="Write the results as evidence for the controls of the frameworks that are on")
async def record_tests(
    tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> RecordOut:
    checks = await _checks(db, tenant)
    enabled = await _enabled(db, tenant)
    results = engine.evaluate_all(checks, await _disabled(db, tenant))
    done = await engine.record(db, tenant, engine.evidence_rows(results, set(enabled)), datetime.now(UTC))
    await audit.note(
        db, tenant, user, "compliance_tests:recorded", "compliance_tests", tenant, written=done["written"], replaced=done["replaced"]
    )
    await db.commit()
    return RecordOut(**done, results=_out(results, enabled, len(checks)))


class ScheduleOut(BaseModel):
    nightly: bool
    last_run_at: datetime | None
    last_result: str | None


class ScheduleIn(BaseModel):
    nightly: bool


@router.get("/schedule", response_model=ScheduleOut, summary="Whether the results are recorded as evidence every night")
async def get_schedule(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> ScheduleOut:
    row = (await db.execute(select(ComplianceTestSchedule).where(ComplianceTestSchedule.tenant_id == tenant))).scalar_one_or_none()
    return ScheduleOut(nightly=bool(row and row.nightly), last_run_at=row.last_run_at if row else None, last_result=row.last_result if row else None)


@router.put("/schedule", response_model=ScheduleOut, summary="Switch nightly recording of the results on or off")
async def save_schedule(
    body: ScheduleIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ScheduleOut:
    row = (await db.execute(select(ComplianceTestSchedule).where(ComplianceTestSchedule.tenant_id == tenant))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = ComplianceTestSchedule(tenant_id=tenant, nightly=body.nightly, updated_by=getattr(user, "email", None), updated_at=now)
        db.add(row)
    else:
        row.nightly, row.updated_by, row.updated_at = body.nightly, getattr(user, "email", None), now
    await audit.note(db, tenant, user, "compliance_tests:schedule", "compliance_tests", tenant, nightly=body.nightly)
    await db.commit()
    return ScheduleOut(nightly=row.nightly, last_run_at=row.last_run_at, last_result=row.last_result)


class LibraryIn(BaseModel):
    disabled: list[str]


@router.put("/library", response_model=TestsOut, summary="Turn tests on or off for the client (the test library)")
async def save_library(
    body: LibraryIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> TestsOut:
    """The tests named are turned off: they leave the counts and write no evidence. Names that are not tests are refused. An empty list turns every test back on."""
    known = {t.id for t in engine.TESTS}
    unknown = [i for i in body.disabled if i not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not tests: {', '.join(unknown[:5])}")
    row = await db.get(Tenant, tenant)
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = dict(row.settings or {})
    settings["compliance_tests"] = {**(settings.get("compliance_tests") or {}), "disabled": sorted(set(body.disabled))}
    row.settings = settings
    await audit.note(db, tenant, user, "compliance_tests:library", "compliance_tests", tenant, disabled=len(settings["compliance_tests"]["disabled"]))
    await db.commit()
    checks = await _checks(db, tenant)
    return _out(engine.evaluate_all(checks, engine.disabled_of(settings)), await _enabled(db, tenant), len(checks))
