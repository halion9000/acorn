"""Controls: every control of the frameworks that are turned on, in one list, with how healthy each one is (Secureframe parity plan, the Controls page).

Health is worked out exactly as on the Compliance overview (``services/compliance_health.py``): healthy when it has accepted evidence under a year old and none rejected, at risk when the evidence is old or only
pending, unhealthy when any evidence was rejected, not tested when there is none. Read with ``reports:read``; ``client_id`` reads one of the caller's clients as the other compliance routes do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.services import compliance_audit as audit
from app.services import compliance_health, csv_export, evidence_age
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
    owner: str | None = None  # who answers for this control, when someone was named (migration 197)


class ControlList(BaseModel):
    enabled: list[str]
    frameworks: list[str]  # the frameworks shown (the ones on, or the one asked for)
    counts: dict[str, int]  # per state, over everything that matches the framework and search (before the state filter)
    total: int  # rows matching every filter
    rows: list[ControlRow]  # at most MAX_ROWS, unhealthy first


def link_for(framework: str) -> str:
    return f"/compliance/{framework.lower().replace('-', '_')}"


def build_rows(
    frameworks: list[str],
    evidence: dict[str, dict[str, dict[str, Any]]],
    now: datetime,
    query: str = "",
    owners: dict[tuple[str, str], str] | None = None,
) -> list[ControlRow]:
    """One row per control of each framework, with its state (pure). ``query`` keeps the controls whose id, title, group or owner contains it (any case). ``owners`` is {(framework, control id): owner}."""
    owners = owners or {}
    q = query.strip().lower()
    out: list[ControlRow] = []
    for fw in frameworks:
        groups = {cid: group for group, cid, _title in CATALOGS[fw]}
        for cid, title in FRAMEWORKS[fw].items():
            if q and q not in f"{cid} {title} {groups.get(cid, '')} {owners.get((fw, cid), '')}".lower():
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
                    owner=owners.get((fw, cid)),
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


async def owners_by_control(db: Any, tenant: Any, frameworks: list[str]) -> dict[tuple[str, str], str]:
    """Who owns each control of the given frameworks: {(framework, control id): owner}."""
    if not frameworks:
        return {}
    rows = (
        await db.execute(
            text("SELECT framework, control_id, owner FROM compliance_control_owners WHERE tenant_id = :t AND framework = ANY(CAST(:fws AS TEXT[]))").bindparams(
                t=tenant, fws=frameworks
            )
        )
    ).all()
    return {(r.framework, r.control_id): r.owner for r in rows}


def inactive_frameworks(enabled: list[str], framework: str | None = None) -> list[str]:
    """The frameworks shown on the Inactive tab (pure): every framework that is not turned on, or the one asked for when it is one of those (none when it is on)."""
    off = [f for f in FRAMEWORKS if f not in enabled]
    if framework:
        return [framework] if framework in off else []
    return off


_ORDER = {"unhealthy": 0, "at_risk": 1, "not_tested": 2, "healthy": 3}


@router.get("", response_model=ControlList, summary="Every control of the frameworks that are on, with its health")
async def list_controls(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    framework: str | None = Query(default=None, max_length=20),
    state: str | None = Query(default=None, pattern="^(healthy|at_risk|unhealthy|not_tested)$"),
    q: str = Query(default="", max_length=100),
    inactive: bool = Query(default=False, description="The controls of the frameworks that are not turned on (the Inactive tab) instead of the ones that are"),
) -> ControlList:
    now = datetime.now(UTC)
    enabled = sorted(
        (await db.execute(select(ComplianceEnabledFramework.framework).where(ComplianceEnabledFramework.tenant_id == tenant))).scalars()
    )
    shown = inactive_frameworks(enabled, framework) if inactive else ([framework] if framework and framework in FRAMEWORKS else ([] if framework else [f for f in enabled if f in FRAMEWORKS]))
    evidence = await evidence_by_control(db, tenant, shown)
    everything = build_rows(shown, evidence, now, q, await owners_by_control(db, tenant, shown))
    counts = dict.fromkeys(compliance_health.STATES, 0)
    for r in everything:
        counts[r.state] += 1
    matching = [r for r in everything if state is None or r.state == state]
    matching.sort(key=lambda r: (_ORDER[r.state], r.framework, r.control_id))
    return ControlList(enabled=enabled, frameworks=shown, counts=counts, total=len(matching), rows=matching[:MAX_ROWS])


@router.get("/export.csv", summary="The controls (every one that matches the filters) as a CSV file")
async def export_controls(
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    framework: str | None = Query(default=None, max_length=20),
    state: str | None = Query(default=None, pattern="^(healthy|at_risk|unhealthy|not_tested)$"),
    q: str = Query(default="", max_length=100),
) -> Response:
    out = await list_controls(tenant, db, user, framework, state, q)
    return csv_export.response(
        "controls.csv",
        [
            "Framework",
            "Control",
            "Title",
            "Group",
            "Health",
            "Accepted evidence",
            "Pending evidence",
            "Rejected evidence",
            "Newest accepted evidence",
            "Age in days",
            "Owner",
        ],
        [
            [r.framework, r.control_id, r.title, r.group, r.state, r.accepted, r.pending, r.rejected, r.newest_evidence, r.age_days, r.owner or ""]
            for r in out.rows
        ],
    )


class OwnerIn(BaseModel):
    owner: str | None = Field(default=None, max_length=120)  # empty or null clears the owner


class OwnerOut(BaseModel):
    framework: str
    control_id: str
    owner: str | None


@router.put("/{framework}/{control_id}/owner", response_model=OwnerOut, summary="Name who owns a control, or clear the owner")
async def set_owner(
    framework: str,
    control_id: str,
    body: OwnerIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> OwnerOut:
    if framework not in FRAMEWORKS or control_id not in FRAMEWORKS[framework]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such control.")
    owner = " ".join((body.owner or "").split())
    if owner:
        await db.execute(
            text(
                """
                INSERT INTO compliance_control_owners (tenant_id, framework, control_id, owner, set_by, updated_at)
                VALUES (:t, :f, :c, :o, :by, now())
                ON CONFLICT (tenant_id, framework, control_id) DO UPDATE SET owner = EXCLUDED.owner, set_by = EXCLUDED.set_by, updated_at = now()
                """
            ).bindparams(t=tenant, f=framework, c=control_id, o=owner, by=getattr(user, "email", None))
        )
    else:
        await db.execute(text("DELETE FROM compliance_control_owners WHERE tenant_id = :t AND framework = :f AND control_id = :c").bindparams(t=tenant, f=framework, c=control_id))
    await audit.note(db, tenant, user, "control:owner_set", "control", f"{framework}:{control_id}", framework=framework, control=control_id, owner=owner or None)
    await db.commit()
    return OwnerOut(framework=framework, control_id=control_id, owner=owner or None)
