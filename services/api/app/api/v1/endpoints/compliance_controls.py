"""Controls: every control of the frameworks that are turned on, in one list, with how healthy each one is (Secureframe parity plan, the Controls page).

Health is worked out exactly as on the Compliance overview (``services/compliance_health.py``): healthy when it has accepted evidence under a year old and none rejected, at risk when the evidence is old or only
pending, unhealthy when any evidence was rejected, not tested when there is none. Read with ``reports:read``; ``client_id`` reads one of the caller's clients as the other compliance routes do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.services import compliance_health, evidence_age
from app.services.compliance_catalog import CATALOGS

router = APIRouter(prefix="/compliance/controls", tags=["compliance"])

MAX_ROWS = 600


class ControlRow(BaseModel):
    framework: str
    control_id: str
    title: str
    group: str
    state: str  # healthy, at_risk, unhealthy or not_tested
    accepted: int
    pending: int
    rejected: int
    newest_evidence: datetime | None  # when the newest accepted evidence was collected
    age_days: int | None
    link: str  # the framework page that holds this control's evidence


class ControlList(BaseModel):
    enabled: list[str]
    frameworks: list[str]  # the frameworks shown (the ones on, or the one asked for)
    counts: dict[str, int]  # per state, over everything that matches the framework and search (before the state filter)
    total: int  # rows matching every filter
    rows: list[ControlRow]  # at most MAX_ROWS, unhealthy first


def link_for(framework: str) -> str:
    return f"/compliance/{framework.lower().replace('-', '_')}"


def build_rows(frameworks: list[str], evidence: dict[str, dict[str, dict[str, Any]]], now: datetime, query: str = "") -> list[ControlRow]:
    """One row per control of each framework, with its state (pure). ``query`` keeps the controls whose id, title or group contains it (any case)."""
    q = query.strip().lower()
    out: list[ControlRow] = []
    for fw in frameworks:
        groups = {cid: group for group, cid, _title in CATALOGS[fw]}
        for cid, title in FRAMEWORKS[fw].items():
            if q and q not in f"{cid} {title} {groups.get(cid, '')}".lower():
                continue
            e = evidence.get(fw, {}).get(cid, {})
            accepted, pending, rejected = int(e.get("accepted", 0)), int(e.get("pending", 0)), int(e.get("rejected", 0))
            newest = e.get("newest")
            out.append(
                ControlRow(
                    framework=fw,
                    control_id=cid,
                    title=title,
                    group=groups.get(cid, ""),
                    state=compliance_health.control_state(accepted, pending, rejected, newest, now),
                    accepted=accepted,
                    pending=pending,
                    rejected=rejected,
                    newest_evidence=newest,
                    age_days=evidence_age.age_days(newest, now) if accepted else None,
                    link=link_for(fw),
                )
            )
    return out


async def evidence_by_control(db: Any, tenant: Any, frameworks: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """The evidence held for each control of the given frameworks: ``{framework: {control id: {accepted, pending, rejected, newest}}}``."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    if not frameworks:
        return out
    rows = (
        await db.execute(
            text(
                """
                SELECT framework, control_id,
                       COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
                       COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                       COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                       MAX(collected_at) FILTER (WHERE status = 'accepted') AS newest
                FROM aisoc_compliance_evidence
                WHERE tenant_id = :t AND framework = ANY(CAST(:fws AS TEXT[]))
                GROUP BY framework, control_id
                """
            ).bindparams(t=tenant, fws=frameworks)
        )
    ).all()
    for r in rows:
        out.setdefault(r.framework, {})[r.control_id] = {
            "accepted": r.accepted,
            "pending": r.pending,
            "rejected": r.rejected,
            "newest": r.newest,
        }
    return out


_ORDER = {"unhealthy": 0, "at_risk": 1, "not_tested": 2, "healthy": 3}


@router.get("", response_model=ControlList, summary="Every control of the frameworks that are on, with its health")
async def list_controls(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    framework: str | None = Query(default=None, max_length=20),
    state: str | None = Query(default=None, pattern="^(healthy|at_risk|unhealthy|not_tested)$"),
    q: str = Query(default="", max_length=100),
) -> ControlList:
    now = datetime.now(UTC)
    enabled = sorted(
        (await db.execute(select(ComplianceEnabledFramework.framework).where(ComplianceEnabledFramework.tenant_id == tenant))).scalars()
    )
    shown = [framework] if framework and framework in FRAMEWORKS else ([] if framework else [f for f in enabled if f in FRAMEWORKS])
    evidence = await evidence_by_control(db, tenant, shown)
    everything = build_rows(shown, evidence, now, q)
    counts = dict.fromkeys(compliance_health.STATES, 0)
    for r in everything:
        counts[r.state] += 1
    matching = [r for r in everything if state is None or r.state == state]
    matching.sort(key=lambda r: (_ORDER[r.state], r.framework, r.control_id))
    return ControlList(enabled=enabled, frameworks=shown, counts=counts, total=len(matching), rows=matching[:MAX_ROWS])
