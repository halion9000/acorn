"""Client onboarding status: for each client, how far it has got from "added" to "everything is flowing" (``GET /client-onboarding``).

Five steps, each read from what is really there and never guessed: tools linked to the client (Client mapping), devices seen, people seen (Microsoft 365), checks run, alerts arriving. A client with a step missing
gets the one next thing to do. Read only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.db.rls_scope import cross_tenant_reads
from app.models.alert import Alert
from app.models.client_alias import ClientAlias
from app.models.device import Device
from app.models.signin import ClientCheckHistory, IdentityMfaUser

router = APIRouter(prefix="/client-onboarding", tags=["clients"])

STEPS: list[tuple[str, str, str]] = [
    ("tools", "Tools linked", "Link this client's tools in Settings, Client mapping."),
    ("devices", "Devices seen", "No device has reported yet: check the RMM or device tool is linked and has synced."),
    ("people", "People seen", "No Microsoft 365 people yet: link the client to CIPP in Client mapping."),
    ("checks", "Checks run", "No tool check has run for this client yet: wait for CORE's next sweep, or press Sync."),
    ("alerts", "Alerts arriving", "No alert has arrived yet: that may just mean a quiet client, or that no detection tool is linked."),
]


class Step(BaseModel):
    key: str
    label: str
    done: bool
    detail: str


class OnboardingRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    steps: list[Step]
    done: int
    total: int
    percent: int
    next_step: str | None
    first_data_at: datetime | None


@dataclass
class Facts:
    tools: int = 0
    devices: int = 0
    people: int = 0
    checks: int = 0
    checks_met: int = 0
    alerts: int = 0
    first_data_at: datetime | None = None


def build_row(client_id: uuid.UUID, name: str, f: Facts) -> OnboardingRow:
    """One client's steps from the facts found: a step is done only when its count is above zero."""
    details = {
        "tools": f"{f.tools} tool{'' if f.tools == 1 else 's'} linked",
        "devices": f"{f.devices} device{'' if f.devices == 1 else 's'}",
        "people": f"{f.people} {'person' if f.people == 1 else 'people'}",
        "checks": f"{f.checks} check{'' if f.checks == 1 else 's'} run, {f.checks_met} met",
        "alerts": f"{f.alerts} alert{'' if f.alerts == 1 else 's'} so far",
    }
    counts = {"tools": f.tools, "devices": f.devices, "people": f.people, "checks": f.checks, "alerts": f.alerts}
    steps = [Step(key=k, label=label, done=counts[k] > 0, detail=details[k]) for k, label, _ in STEPS]
    done = sum(1 for s in steps if s.done)
    missing = next((hint for (k, _l, hint), s in zip(STEPS, steps, strict=True) if not s.done), None)
    return OnboardingRow(
        client_id=client_id,
        client_name=name,
        steps=steps,
        done=done,
        total=len(steps),
        percent=round(100 * done / len(steps)),
        next_step=missing,
        first_data_at=f.first_data_at,
    )


@router.get("", response_model=list[OnboardingRow])
async def client_onboarding(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = Query(default=None)
) -> list[OnboardingRow]:
    """Every client (or one), least onboarded first, so the ones that need attention are at the top."""
    return await _onboarding_rows(user, db, client_id)


def onboarding_csv(rows: list[OnboardingRow]) -> str:
    """The onboarding table as CSV: one row per client, a yes or no for each step, how far along, and the next thing to do. A cell that would run as a formula is made text."""
    import csv
    import io

    from app.api.v1.endpoints.devices import csv_cell

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Client", "Percent", "Steps done", "Steps", *[label for _k, label, _h in STEPS], "Next step", "First data"])
    for r in rows:
        by_key = {s.key: s for s in r.steps}
        writer.writerow(
            [
                csv_cell(r.client_name),
                r.percent,
                r.done,
                r.total,
                *["yes" if by_key[k].done else "no" for k, _l, _h in STEPS if k in by_key],
                csv_cell(r.next_step),
                r.first_data_at.isoformat() if r.first_data_at else "",
            ]
        )
    return out.getvalue()


@router.get("/export.csv", summary="The client onboarding table as a CSV file")
async def export_client_onboarding(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = Query(default=None)
) -> Response:
    """The same rows the page shows (least onboarded first), as a file."""
    rows = await _onboarding_rows(user, db, client_id)
    return Response(
        content=onboarding_csv(rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="client-onboarding.csv"'}
    )


async def _onboarding_rows(user: Any, db: Any, client_id: uuid.UUID | None) -> list[OnboardingRow]:
    scope, names = await _scope(db, user.tenant_id, client_id)
    clients = [t for t in scope if t != user.tenant_id]
    facts = {t: Facts() for t in clients}
    first: dict[uuid.UUID, list[datetime]] = {t: [] for t in clients}
    async with cross_tenant_reads(db):
        for tid, n in (
            await db.execute(
                select(ClientAlias.child_tenant_id, func.count(func.distinct(ClientAlias.vendor)))
                .where(ClientAlias.tenant_id == user.tenant_id, ClientAlias.child_tenant_id.in_(clients), ClientAlias.ignored.is_(False))
                .group_by(ClientAlias.child_tenant_id)
            )
        ).all():
            facts[tid].tools = int(n)
        for tid, n, at in (
            await db.execute(
                select(Device.tenant_id, func.count(), func.min(Device.first_seen))
                .where(Device.tenant_id.in_(clients))
                .group_by(Device.tenant_id)
            )
        ).all():
            facts[tid].devices = int(n)
            if at:
                first[tid].append(at)
        for tid, n in (
            await db.execute(
                select(IdentityMfaUser.tenant_id, func.count())
                .where(IdentityMfaUser.tenant_id.in_(clients))
                .group_by(IdentityMfaUser.tenant_id)
            )
        ).all():
            facts[tid].people = int(n)
        for tid, n, met in (
            await db.execute(
                select(
                    ClientCheckHistory.tenant_id,
                    func.count(func.distinct(ClientCheckHistory.key)),
                    func.count(func.distinct(ClientCheckHistory.key)).filter(ClientCheckHistory.status == "met"),
                )
                .where(ClientCheckHistory.tenant_id.in_(clients))
                .group_by(ClientCheckHistory.tenant_id)
            )
        ).all():
            facts[tid].checks, facts[tid].checks_met = int(n), int(met)
        for tid, n, at in (
            await db.execute(
                select(Alert.tenant_id, func.count(), func.min(Alert.created_at))
                .where(Alert.tenant_id.in_(clients))
                .group_by(Alert.tenant_id)
            )
        ).all():
            facts[tid].alerts = int(n)
            if at:
                first[tid].append(at)
    for t in clients:
        facts[t].first_data_at = min(first[t]) if first[t] else None
    rows = [build_row(t, names.get(t, "Client"), facts[t]) for t in clients]
    return sorted(rows, key=lambda r: (r.done, r.client_name.lower()))
