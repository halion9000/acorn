"""CORE reports what it forwarded, so the Connectors page can show it.

CORE reads the tools it holds credentials for (Huntress, Blumira, ...) and posts the records to the push inbox (``/v1/inbox/{token}``). That path carries the data;
it says nothing about whether each source is healthy, so nothing would ever fill in the ``connectors`` columns the Connectors page reads (health, last sync, events
ingested, errors). After each run CORE therefore posts a short report here, and each source becomes (or updates) one row of type ``core_feed``.

``POST /api/v1/inbox/core-feed/{tenant_token}/status`` is authenticated by the secret in the path, exactly like the ITSM webhooks (``inbox_itsm.py``): no session, no
API key. Only the tenant's ``core-feed`` token (template ``generic-json``, label ``core-feed``, not revoked) is accepted, so a token minted for any other webhook
cannot write here. The report can only create or update this tenant's own ``core_feed`` rows; it cannot touch any other connector.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import ARRAY, Text, cast, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB

from app.api.v1.deps import DBSession
from app.core.logging import safe_log_value
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.db.rls_sessions import adopt_tenant
from app.models.alert import Alert
from app.models.connector import Connector
from app.models.finance_halo_snapshot import FinanceHaloSnapshot
from app.models.finance_profit import FinanceCostEntry, FinanceCostTransactions, FinancePnlMonth, FinanceProfitSnapshot, FinanceProfitTickets, FinanceQboSales, FinanceVendorCost
from app.models.metric_dataset import DATASET_KEYS, MetricDataset, merge_dataset
from app.models.tenant import Tenant
from app.models.ticket_stats import CsatSnapshot, TicketStatsSnapshot
from app.models.vendor_action import VendorAction
from app.services import core_approvals, core_heartbeat
from app.services import vcio_risk_tickets as vcio_tickets
from app.services.alert_settle import case_has_no_other_open_alert, closed_in_tool, has_open_ticket, tickets_all_closed
from app.services.alert_status import FINISHED_ALERT_STATUSES
from app.services.alert_ticket_rules import link_created_ticket
from app.services.client_mapping import IncomingClient, upsert_clients
from app.services.connector_run_log import record_if_changed
from app.services.core_feed_cases import close_finished_cases, open_cases_for_new_alerts
from app.services.core_feed_sla import record_closure_events
from app.services.iocs_from_alerts import sync_children_throttled as sync_iocs_throttled
from app.services.mssp_snapshots import snapshot_children_throttled
from app.services.quarantine_release import ELSEWHERE, UID_PREFIX, note_quarantine_released, note_sender_allowed, store_quarantine_check
from app.services.vendor_actions import CLAIMED_TTL, PENDING_TTL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

CORE_FEED_TYPE = "core_feed"
CORE_FEED_LABEL = "core-feed"
CORE_FEED_TEMPLATE = "generic-json"
_CATEGORIES = ("siem", "edr", "cloud", "iam", "saas", "audit", "vcs", "ndr", "network")


class SourceReport(BaseModel):
    """One source's outcome for CORE's latest run."""

    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$", description="CORE's id for the source, e.g. ``huntress``.")
    name: str | None = Field(default=None, max_length=120, description="Display name for a new row; ignored for an existing one.")
    category: Literal["siem", "edr", "cloud", "iam", "saas", "audit", "vcs", "ndr", "network"] = "saas"
    # "warning": the alerts came through, but a side job (devices, clients, ticket links) failed; ``message`` says which.
    status: Literal["ok", "warning", "error"]
    # "devices" for a tool that only supplies devices (DNSFilter, ScreenConnect...): its card shows how many devices the last sync read instead of an event count that would stay 0.
    kind: Literal["alerts", "devices"] = "alerts"
    fetched: int = Field(default=0, ge=0, le=1_000_000)
    sent: int = Field(default=0, ge=0, le=1_000_000, description="Records A.C.O.R.N accepted in this run.")
    message: str | None = Field(
        default=None,
        max_length=300,
        description="Why a run failed, in CORE's words (already stripped of tokens and URLs). Shown on the connector card.",
    )


class ApprovalNote(BaseModel):
    """One approval waiting for the owner in CORE. Only what the bell shows."""

    role: str = Field(max_length=40)
    summary: str = Field(max_length=200)
    days_left: int = Field(ge=0, le=30, description="Whole days before CORE takes the card off the list.")


class CoreInfoIn(BaseModel):
    commit: str = Field(max_length=40)
    uptime_seconds: int = Field(ge=0, le=10**9)
    sweeps: int = Field(ge=0, le=10**9)


class StatusReport(BaseModel):
    sources: list[SourceReport] = Field(max_length=50)
    # What CORE says about itself (its commit, how long it has been up, how many feed passes it has made); absent from an older CORE.
    core: CoreInfoIn | None = None
    # CORE's approvals waiting right now; absent from an older CORE (then nothing is stored or changed), an empty list when none are waiting.
    approvals: list[ApprovalNote] | None = Field(default=None, max_length=50)


class StatusResponse(BaseModel):
    updated: int


async def _verify_core_feed_token(db: Any, token: str) -> Any:
    """The tenant of an active ``core-feed`` token, or 401. A read across tenants by nature (the tenant is learned FROM the token)."""
    async with cross_tenant_reads(db):
        row = (
            await db.execute(
                text(
                    """
                    SELECT tenant_id
                    FROM tenant_inbox_tokens
                    WHERE token = :token AND revoked_at IS NULL AND template_id = :template AND label = :label
                    """
                ).bindparams(token=token, template=CORE_FEED_TEMPLATE, label=CORE_FEED_LABEL)
            )
        ).fetchone()
    if row is None:
        # One answer for "no such token", "revoked" and "a token for something else": don't tell a caller which.
        logger.warning("inbox_core_feed.token_rejected", extra={"token_fingerprint": safe_log_value(f"...{token[-6:]}")})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked inbox token")
    return row.tenant_id


async def _scope_ids(db: Any, owner: Any) -> list[Any]:
    """The tenant that owns the feed, then its client tenants. A mapped client's alerts are stored under the client's own tenant (fusion's client routing), so anything that
    looks for "this feed's alerts" has to look there too. Only real children of the owner qualify: the token never reaches any other tenant."""
    children = (await db.execute(select(Tenant.id).where(Tenant.parent_tenant_id == owner))).scalars().all()
    return [owner, *children]


async def _across(db: Any, owner: Any, work: Any, tenants: list[Any] | None = None) -> list[Any]:
    """Run ``work(tenant_id)`` once per tenant (the whole scope, or just ``tenants``), each inside that tenant's row-level-security scope (restored afterwards). Returns the results in order."""
    results = []
    for tid in tenants if tenants is not None else await _scope_ids(db, owner):
        async with acting_as_tenant(db, tid):
            results.append(await work(tid))
    return results


async def _tenants_holding(db: Any, owner: Any, uids: list[str]) -> list[tuple[Any, set[str]]]:
    """For each tenant in the feed's scope that has an alert for any of these incident ids, which of the ids it holds (scope order): ONE query.

    A report used to be applied item by item in every client tenant of the owner. With 240 clients, a few hundred items was tens of thousands of statements, each inside its own
    row-level-security scope, and CORE gave up after 30 seconds. An incident normally lives in one tenant, so ask once where each one is and give every tenant only its own items.
    The lookup reads across the scope on purpose (it is what finds the tenants), and returns only tenant ids that are already in it: the token never reaches any other tenant.
    """
    scope = await _scope_ids(db, owner)
    wanted = sorted(set(uids))
    if not wanted:
        return []
    uid_expr = Alert.raw_event["finding"]["uid"].astext
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(select(Alert.tenant_id, uid_expr).where(Alert.tenant_id.in_(scope), uid_expr.in_(wanted)).distinct())
        ).all()
    held: dict[Any, set[str]] = {}
    for tid, uid in rows:
        held.setdefault(tid, set()).add(uid)
    return [(tid, held[tid]) for tid in scope if tid in held]


async def apply_report(db: Any, tenant_id: Any, report: StatusReport, now: datetime | None = None) -> int:
    """Create or update one ``core_feed`` row per reported source. The caller owns the transaction. Returns how many sources were applied."""
    now = now or datetime.now(UTC)
    applied = 0
    for src in report.sources:
        row = (
            await db.execute(
                select(Connector).where(
                    Connector.tenant_id == tenant_id,
                    Connector.connector_type == CORE_FEED_TYPE,
                    Connector.connector_config["vendor"].astext == src.vendor,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = Connector(
                tenant_id=tenant_id,
                name=(src.name or f"{src.vendor.replace('-', ' ').title()}")[:120] + " (via CORE)",
                connector_type=CORE_FEED_TYPE,
                category=src.category,
                is_enabled=True,
                auth_config={},
                connector_config={"vendor": src.vendor, "managed_by": "core"},
                tags=["core-feed"],
                health_status="unknown",
                events_ingested=0,
                events_dropped=0,
                error_count=0,
            )
            db.add(row)
            await db.flush()

        values: dict[str, Any] = {"last_health_check": now, "updated_at": now}
        config = dict(row.connector_config or {})
        if src.status in ("error", "warning") and src.message and src.message.strip():
            config.update(last_error=src.message.strip(), last_error_at=now.isoformat())
        else:
            config.pop("last_error", None)
            config.pop("last_error_at", None)
        if src.kind == "devices":
            config.update(kind="devices", devices=src.fetched)
        else:
            config.pop("kind", None)
            config.pop("devices", None)
        if config != (row.connector_config or {}):
            values["connector_config"] = config
        if src.status in ("ok", "warning"):
            values.update(
                health_status="healthy" if src.status == "ok" else "degraded",
                last_sync=now,
                events_ingested=Connector.events_ingested + src.sent,
                last_outage_at=None,
            )
            if src.sent > 0:
                values.update(last_event_at=now, last_event_kind="core-feed")
        else:
            values.update(
                health_status="unhealthy",
                error_count=Connector.error_count + 1,
                last_outage_at=func.coalesce(Connector.last_outage_at, now),
            )
        await db.execute(update(Connector).where(Connector.id == row.id).values(**values))
        # The card keeps only the latest message; the log keeps the history (an entry only when status or message changed).
        await record_if_changed(
            db,
            tenant_id,
            row.id,
            status=src.status,
            message=src.message if src.status != "ok" else None,
            fetched=src.fetched,
            sent=src.sent,
            now=now,
        )
        applied += 1
    return applied


@router.post("/core-feed/{tenant_token}/status", response_model=StatusResponse)
async def report_core_feed_status(tenant_token: str, body: StatusReport, db: DBSession) -> StatusResponse:
    """Record CORE's latest run for each source it forwards."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    applied = await apply_report(db, tenant_id, body)
    await db.commit()
    if body.approvals is not None:
        await core_approvals.remember(tenant_id, [a.model_dump() for a in body.approvals])
    if body.core is not None:
        await core_heartbeat.remember(tenant_id, body.core.commit, body.core.uptime_seconds, body.core.sweeps)
    # Refresh the per-client numbers the MSSP overview shows. Best effort: it must never fail the status report itself.
    try:
        if await snapshot_children_throttled(db, tenant_id):
            await db.commit()
    except Exception:
        logger.exception("mssp.snapshot_refresh_failed")
        await db.rollback()
    # Open a case for each new high/critical alert that has none. Also best effort.
    try:
        if await open_cases_for_new_alerts(db, tenant_id):
            await db.commit()
    except Exception:
        logger.exception("core_feed.auto_cases_failed")
        await db.rollback()
    # Close the cases A.C.O.R.N opened itself once every alert in them is closed and nobody has taken them. Also best effort.
    try:
        if await close_finished_cases(db, tenant_id):
            await db.commit()
    except Exception:
        logger.exception("core_feed.auto_close_cases_failed")
        await db.rollback()
    # Record public IPs and file hashes seen on alerts as Threat Intel indicators. Also best effort.
    try:
        if await sync_iocs_throttled(db, tenant_id):
            await db.commit()
    except Exception:
        logger.exception("core_feed.iocs_from_alerts_failed")
        await db.rollback()
    return StatusResponse(updated=applied)


# ---- Sync pressed on a connector card ---------------------------------------------------------------------------------------------------------------------------------

# A request nobody collected (CORE was off) goes stale instead of firing hours later, when the person has long stopped waiting.
SYNC_REQUEST_TTL = timedelta(minutes=10)


class SyncClaimResponse(BaseModel):
    vendors: list[str]


async def claim_sync_requests_for(db: Any, tenant_id: Any, now: datetime | None = None) -> list[str]:
    """The tools whose Sync button was pressed recently, handed over once: the request is cleared as it is collected, so the next check finds nothing. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(Connector.id, Connector.connector_config).where(
                Connector.tenant_id == tenant_id,
                Connector.connector_type == CORE_FEED_TYPE,
                Connector.connector_config.has_key("sync_requested_at"),  # noqa: W601
            )
        )
    ).all()
    vendors: list[str] = []
    for row in rows:
        config = row.connector_config or {}
        try:
            asked = datetime.fromisoformat(str(config.get("sync_requested_at")))
        except ValueError:
            asked = None
        if asked is not None and asked.tzinfo is None:
            asked = asked.replace(tzinfo=UTC)
        if asked is not None and now - asked <= SYNC_REQUEST_TTL and isinstance(config.get("vendor"), str):
            vendors.append(config["vendor"])
        await db.execute(
            update(Connector).where(Connector.id == row.id).values(connector_config=Connector.connector_config.op("-")("sync_requested_at"))
        )
    vendors.extend(await claim_settings_sync_requests(db, tenant_id, now))
    return sorted(set(vendors))


async def claim_settings_sync_requests(db: Any, tenant_id: Any, now: datetime) -> list[str]:
    """Sync requests left on the organization's settings (the HubSpot automations have no connector card to hold one), recent ones handed over and every one cleared. The caller owns the transaction."""
    settings = (await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))).scalar_one_or_none()
    asked = (settings or {}).get("sync_requests") if isinstance(settings, dict) else None
    if not isinstance(asked, dict) or not asked:
        return []
    out: list[str] = []
    for vendor, when in asked.items():
        try:
            at = datetime.fromisoformat(str(when))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if now - at <= SYNC_REQUEST_TTL and isinstance(vendor, str):
            out.append(vendor)
    await db.execute(update(Tenant).where(Tenant.id == tenant_id).values(settings=Tenant.settings.op("-")("sync_requests")))
    return out


@router.post("/core-feed/{tenant_token}/sync-requests/claim", response_model=SyncClaimResponse)
async def claim_core_feed_sync_requests(tenant_token: str, db: DBSession) -> SyncClaimResponse:
    """CORE asks, about every 15 seconds, which tools to sync now."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    vendors = await claim_sync_requests_for(db, tenant_id)
    await db.commit()
    return SyncClaimResponse(vendors=vendors)


# ---- closed in the vendor's own portal --------------------------------------------------------------------------------------------------------------------------------


_UID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,120}$"
# A closure names the id the alert was stored under, and some of those are a vendor's own text: Exchange names a quarantined message ``guid\guid`` and a message id is ``<text@host>``. Refusing
# one refused the whole report, so every other CIPP closure sent with it (Defender, risky sign-ins, phishing reports) was turned away with it, every round. The id is only ever a bound value
# in a query (never part of the SQL or of a pattern), so these characters are safe; spaces, quotes, semicolons and wildcards are still refused.
_CLOSED_UID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_.\-\\@<>+=/~]{0,399}$"
_CLOSED_CHUNK = 100


class ClosedItem(BaseModel):
    uid: str = Field(pattern=_CLOSED_UID_PATTERN, description="The incident's ``finding.uid`` as CORE sent it, e.g. ``huntress:4821``.")
    state: str | None = Field(
        default=None, max_length=60, description="The vendor's own word for it, e.g. ``resolved`` or ``REMEDIATED``; shown on the alert."
    )


class ClosedReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    closed: list[ClosedItem] = Field(max_length=500)


class ClosedResponse(BaseModel):
    resolved: int


# A vendor's incident ids normally start with its own name (``huntress:4821``). CORE's CIPP feed (vendor ``cipp``) carries four kinds of record with their own prefixes; a closure for any of them must match too.
EXTRA_UID_PREFIXES: dict[str, tuple[str, ...]] = {"cipp": ("defender:", "entra-risk:", "phish-report:", "quarantine-release:")}


def closed_prefixes(vendor: str) -> tuple[str, ...]:
    """The incident-id prefixes a closure reported for ``vendor`` may match."""
    return (f"{vendor}:", f"{vendor}-", *EXTRA_UID_PREFIXES.get(vendor, ()))


async def note_released_elsewhere(db: Any, tenant_id: Any, uids: list[str], now: datetime) -> int:
    """For quarantine-release alerts whose message Microsoft 365 now shows as released (by someone else): record it on the alert and queue the ticket note. Safe to run again. Returns how many alerts were noted."""
    ids = (
        (await db.execute(select(Alert.id).where(Alert.tenant_id == tenant_id, Alert.raw_event["finding"]["uid"].astext.in_(uids))))
        .scalars()
        .all()
    )
    noted = 0
    for alert_id in ids:
        if await note_quarantine_released(db, tenant_id, alert_id, now, by=ELSEWHERE, resolve_any_open=False):
            noted += 1
    return noted


async def apply_closed(db: Any, tenant_id: Any, report: ClosedReport, now: datetime | None = None) -> int:
    """Resolve this tenant's alerts whose incident the vendor has closed. The caller owns the transaction. Returns how many alerts changed.

    Deliberately narrow: only alerts still ``new`` (nobody has acted on them) are touched, so an analyst's own decision is never overridden; it can only CLOSE, never
    reopen; and an alert is matched on the incident id the inbox template keeps at ``raw_event.finding.uid``, within this tenant. Alerts imported before that was kept have no id and are not matched. The vendor's state is kept on the alert (and as a tag).
    """
    now = now or datetime.now(UTC)
    # A vendor's uids are ``huntress:4821`` (incident reports) but also ``huntress-escalation:9`` and ``huntress-signal:3``: all of them are the vendor's own, so all can be closed.
    prefixes = closed_prefixes(report.vendor)
    by_uid = {item.uid: item.state for item in report.closed if item.uid.startswith(prefixes)}
    uids = sorted(by_uid)
    changed = 0
    for i in range(0, len(uids), _CLOSED_CHUNK):
        chunk = uids[i : i + _CLOSED_CHUNK]
        note = {
            "closed_in_vendor": {
                "vendor": report.vendor,
                "at": now.isoformat(),
                "states": sorted({str(by_uid[u]) for u in chunk if by_uid[u]}),
            }
        }
        in_chunk = (Alert.tenant_id == tenant_id, Alert.raw_event["finding"]["uid"].astext.in_(chunk))
        tag = literal([f"closed-in-{report.vendor}"], type_=JSONB)
        # Closed in the tool, nobody has acted on it, and no ticket of it is still open: resolved. (An alert with no ticket at all has none open.)
        result = await db.execute(
            update(Alert)
            .where(*in_chunk, Alert.status == "new", ~has_open_ticket())
            .values(
                status="resolved",
                resolved_at=now,  # without it a vendor-closed alert drops out of every MTTR figure that measures created_at to resolved_at
                updated_at=now,
                enrichment_data=Alert.enrichment_data.op("||")(literal(note, type_=JSONB)),
                tags=Alert.tags.op("||")(tag),
            )
        )
        changed += result.rowcount or 0
        # The rest that are still open: remember the tool closed them (the alert page says so, and the last ticket to close can then close the alert) ...
        await db.execute(
            update(Alert)
            .where(*in_chunk, Alert.status.notin_(FINISHED_ALERT_STATUSES))
            .values(enrichment_data=Alert.enrichment_data.op("||")(literal(note, type_=JSONB)))
        )
        # ... and close the ones, whatever stage they are at, whose tickets are all closed too.
        result = await db.execute(
            update(Alert)
            .where(*in_chunk, Alert.status.notin_(FINISHED_ALERT_STATUSES), tickets_all_closed())
            .values(status="resolved", resolved_at=now, updated_at=now, tags=Alert.tags.op("||")(tag))
        )
        changed += result.rowcount or 0
    released = [u for u in uids if u.startswith(UID_PREFIX) and str(by_uid[u]).lower() == "released"]
    if released:
        await note_released_elsewhere(db, tenant_id, released, now)
    return changed


@router.post("/core-feed/{tenant_token}/closed", response_model=ClosedResponse)
async def report_core_feed_closed(tenant_token: str, body: ClosedReport, db: DBSession) -> ClosedResponse:
    """Mark alerts resolved when CORE reports their incidents closed in the vendor's own portal."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    prefixes = closed_prefixes(body.vendor)
    holders = await _tenants_holding(db, tenant_id, [i.uid for i in body.closed if i.uid.startswith(prefixes)])
    held = dict(holders)
    changed = await _across(
        db,
        tenant_id,
        lambda tid: apply_closed(db, tid, body.model_copy(update={"closed": [i for i in body.closed if i.uid in held[tid]]}), now),
        tenants=[tid for tid, _ in holders],
    )
    resolved = sum(changed)
    if resolved:
        # Give the SLA page the timing for what was just closed. Best effort: it must never undo the closures themselves. Only tenants where something was resolved.
        async def sla(tid: Any) -> int:
            try:
                async with db.begin_nested():
                    return await record_closure_events(db, tid, body.vendor, now)
            except Exception:
                logger.exception("core_feed.sla_events_failed")
                return 0

        await _across(db, tenant_id, sla, tenants=[tid for (tid, _), n in zip(holders, changed, strict=True) if n])
    await db.commit()
    return ClosedResponse(resolved=resolved)


# --- Incident state and vendor actions -------------------------------------------------------------------------------------------------------------------------
# CORE reports each OPEN incident's current state (status, remediation plan, the ticket the vendor opened in the PSA) so A.C.O.R.N can show it; an analyst's approve /
# reject / resolve is queued as a ``vendor_actions`` row (``alert_vendor_actions.py``), CORE collects it here, carries it out at the vendor (CORE holds the key; A.C.O.R.N never does)
# and reports the outcome. Same path-token authentication as the routes above.


class _Param(BaseModel):
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class _Remediation(BaseModel):
    id: int
    type: str | None = Field(default=None, max_length=30)
    action: str | None = Field(default=None, max_length=200)
    parameters: list[_Param] = Field(default_factory=list, max_length=20)
    status: str | None = Field(default=None, max_length=30)


class StateItem(BaseModel):
    uid: str = Field(pattern=_UID_PATTERN)
    status: str = Field(max_length=40, description="The vendor's status for the incident, e.g. ``sent``.")
    remediations: list[_Remediation] = Field(default_factory=list, max_length=50)
    psa_ticket_eids: list[str] = Field(
        default_factory=list, max_length=20, description="Ticket ids the vendor opened in the PSA for this incident."
    )


class StateReport(BaseModel):
    vendor: Literal["huntress"]
    items: list[StateItem] = Field(max_length=500)


class StateResponse(BaseModel):
    updated: int


async def apply_state(db: Any, tenant_id: Any, report: StateReport, now: datetime | None = None) -> int:
    """Store each incident's reported state on its alert (``enrichment_data.vendor_state``). The caller owns the transaction. Returns how many alerts were updated."""
    now = now or datetime.now(UTC)
    prefix = f"{report.vendor}:"
    updated = 0
    for item in report.items:
        if not item.uid.startswith(prefix):
            continue
        state = {
            "vendor_state": {
                "vendor": report.vendor,
                "at": now.isoformat(),
                "status": item.status,
                "remediations": [r.model_dump() for r in item.remediations],
                "psa_ticket_eids": [str(t)[:120] for t in item.psa_ticket_eids],
            }
        }
        result = await db.execute(
            update(Alert)
            .where(Alert.tenant_id == tenant_id, Alert.raw_event["finding"]["uid"].astext == item.uid)
            .values(enrichment_data=Alert.enrichment_data.op("||")(literal(state, type_=JSONB)))
        )
        updated += result.rowcount or 0
    return updated


@router.post("/core-feed/{tenant_token}/state", response_model=StateResponse)
async def report_core_feed_state(tenant_token: str, body: StateReport, db: DBSession) -> StateResponse:
    """Record the current state of open vendor incidents, so the alert can show the remediation plan and offer the right actions."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    prefix = f"{body.vendor}:"
    holders = await _tenants_holding(db, tenant_id, [i.uid for i in body.items if i.uid.startswith(prefix)])
    held = dict(holders)
    updated = sum(
        await _across(
            db,
            tenant_id,
            lambda tid: apply_state(db, tid, body.model_copy(update={"items": [i for i in body.items if i.uid in held[tid]]})),
            tenants=[tid for tid, _ in holders],
        )
    )
    await db.commit()
    return StateResponse(updated=updated)


# "core" is CORE's own queue: what A.C.O.R.N asks CORE to do itself rather than at a vendor (the Run script requests).
class ClaimRequest(BaseModel):
    vendor: Literal["huntress", "blumira", "fieldeffect", "core"]


class ClaimedAction(BaseModel):
    id: uuid.UUID
    action: Literal[
        "approve",
        "reject",
        "resolve",
        "run_script",
        "revoke_sessions",
        "disable_user",
        "enable_user",
        "bec_search",
        "create_ticket",
        "release_quarantine",
        "ticket_note",
        "quarantine_check",
        "allow_sender",
        "create_halo_user",
        "addigy_push",
        "sc_command",
        "ninja_deploy",
        "halo_billing_update",
        "user_lookup",
        "directory_lookup",
        "mailbox_rules_lookup",
    ]
    incident_uid: str
    params: dict[str, Any]


class ClaimResponse(BaseModel):
    actions: list[ClaimedAction]


async def claim_actions(db: Any, tenant_id: Any, vendor: str, now: datetime | None = None) -> list[VendorAction]:
    """Hand CORE this tenant's pending actions, each at most once. The caller owns the transaction.

    First the housekeeping that keeps the queue honest: a pending action older than its time-to-live is failed as expired (it must never fire late), and a claimed one CORE never
    answered is failed. Then pending actions are claimed in one statement (``pending`` -> ``claimed``), so two overlapping polls cannot both receive the same row.
    """
    now = now or datetime.now(UTC)
    await db.execute(
        update(VendorAction)
        .where(VendorAction.tenant_id == tenant_id, VendorAction.status == "pending", VendorAction.created_at < now - PENDING_TTL)
        .values(status="failed", result_message="Expired before CORE collected it; request it again.", finished_at=now)
    )
    await db.execute(
        update(VendorAction)
        .where(VendorAction.tenant_id == tenant_id, VendorAction.status == "claimed", VendorAction.claimed_at < now - CLAIMED_TTL)
        .values(status="failed", result_message="CORE did not report a result.", finished_at=now)
    )
    rows = (
        (
            await db.execute(
                update(VendorAction)
                .where(VendorAction.tenant_id == tenant_id, VendorAction.vendor == vendor, VendorAction.status == "pending")
                .values(status="claimed", claimed_at=now)
                .returning(VendorAction)
            )
        )
        .scalars()
        .all()
    )
    return sorted(rows, key=lambda r: r.created_at)


# The poll normally works only in the tenants that hold a pending or claimed action. As a safety net, once a minute it works in every tenant of the scope anyway: the lookup reads across tenants, which
# row-level security may one day refuse (it then sees nothing), and an action must then be delayed a minute at worst, never lost.
FULL_CLAIM_EVERY_SECONDS = 60.0
_last_full_claim: dict[Any, float] = {}


@router.post("/core-feed/{tenant_token}/actions/claim", response_model=ClaimResponse)
async def claim_core_feed_actions(tenant_token: str, body: ClaimRequest, db: DBSession) -> ClaimResponse:
    """CORE collects the actions analysts have asked for. Each is handed out once."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    # CORE asks every few seconds, for each vendor, and almost always there is nothing to hand out. Running three statements in every one of the owner's 200 or so client tenants made each ask take
    # several seconds. So ask ONCE which tenants hold any pending or claimed action (the only ones the expiry housekeeping or the claim could touch) and do the work for those alone.
    scope = await _scope_ids(db, tenant_id)
    async with cross_tenant_reads(db):
        holding = set(
            (
                await db.execute(
                    select(VendorAction.tenant_id)
                    .where(VendorAction.tenant_id.in_(scope), VendorAction.status.in_(("pending", "claimed")))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
    moment = time.monotonic()
    everywhere = moment - _last_full_claim.get(tenant_id, -1e12) >= FULL_CLAIM_EVERY_SECONDS
    if everywhere:
        _last_full_claim[tenant_id] = moment
    rows = sorted(
        [
            r
            for got in await _across(
                db,
                tenant_id,
                lambda tid: claim_actions(db, tid, body.vendor),
                tenants=scope if everywhere else [t for t in scope if t in holding],
            )
            for r in got
        ],
        key=lambda r: r.created_at,
    )
    await db.commit()
    return ClaimResponse(
        actions=[ClaimedAction(id=r.id, action=r.action, incident_uid=r.incident_uid, params=r.params or {}) for r in rows]  # type: ignore[arg-type]
    )


# The most JSON a read request's answer may hold (CORE trims to well under this).
MAX_RESULT_DATA_CHARS = 60_000


class ActionResult(BaseModel):
    status: Literal["done", "failed"]
    message: str | None = Field(default=None, max_length=2000)
    # For a create_ticket action that worked: the number HaloPSA gave the new ticket (digits). It is linked to the alert.
    ticket_id: str | None = Field(default=None, pattern=r"^[0-9]{1,12}$")
    # For a release_quarantine action: CORE looked first and the message had already been released by someone else, so it sent nothing.
    already_released: bool = False
    # For a read request (user_lookup): the structured answer. Kept as sent, at most MAX_RESULT_DATA_CHARS of JSON.
    data: dict[str, Any] | None = None

    @field_validator("data")
    @classmethod
    def _data_is_small(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v, default=str)) > MAX_RESULT_DATA_CHARS:
            raise ValueError(f"data is longer than {MAX_RESULT_DATA_CHARS} characters")
        return v


class ActionResultResponse(BaseModel):
    recorded: bool


@router.post("/core-feed/{tenant_token}/actions/{action_id}/result", response_model=ActionResultResponse)
async def report_core_feed_action_result(
    tenant_token: str, action_id: uuid.UUID, body: ActionResult, db: DBSession
) -> ActionResultResponse:
    """CORE reports how a claimed action went. Only a claimed action of this tenant can be answered, once."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = None
    for tid in await _scope_ids(db, tenant_id):
        async with acting_as_tenant(db, tid):
            row = (
                await db.execute(
                    update(VendorAction)
                    .where(VendorAction.id == action_id, VendorAction.tenant_id == tid, VendorAction.status == "claimed")
                    .values(status=body.status, result_message=body.message, result_data=body.data, finished_at=now)
                    .returning(VendorAction.alert_id, VendorAction.action, VendorAction.params, VendorAction.incident_uid)
                )
            ).first()
            if row is not None:
                if body.status == "done" and row.action == "allow_sender" and row.alert_id is not None:
                    await note_sender_allowed(
                        db,
                        tid,
                        row.alert_id,
                        now,
                        by=str((row.params or {}).get("requested_by_name") or "A.C.O.R.N")[:200],
                        sender=str((row.params or {}).get("sender_address") or "")[:320],
                    )
                if body.status == "done" and row.action == "quarantine_check" and row.alert_id is not None and body.message:
                    await store_quarantine_check(db, tid, row.alert_id, body.message, now)
                if body.status == "done" and row.action == "release_quarantine" and row.alert_id is not None:
                    by = ELSEWHERE if body.already_released else str((row.params or {}).get("requested_by_name") or "A.C.O.R.N")[:200]
                    await note_quarantine_released(db, tid, row.alert_id, now, by=by)
                if body.status == "done" and row.action == "create_ticket" and body.ticket_id and row.alert_id is not None:
                    await link_created_ticket(db, tid, row.alert_id, body.ticket_id, now)
                if body.status == "done" and row.action == "create_ticket" and body.ticket_id and row.alert_id is None:
                    # A ticket opened for a BEC search (it has no alert): note its number on the search and its case.
                    from app.services.bec_followup import on_ticket_created  # noqa: PLC0415

                    await on_ticket_created(db, tid, row.incident_uid, body.ticket_id, now)
                    # Or for a Client Risk Score question: record its number on the question's line and queue its private note.
                    await vcio_tickets.on_created(db, tid, row.incident_uid, body.ticket_id, now)
                if body.status == "failed" and row.action == "create_ticket" and row.alert_id is None:
                    await vcio_tickets.on_failed(db, tid, row.incident_uid, body.message, now)
                if body.status == "done" and row.action == "resolve":
                    # The vendor accepted the resolution: mirror it now rather than waiting for the next closed-incident sweep. Same narrow rule as ``apply_closed``: never override an analyst's decision.
                    await db.execute(
                        update(Alert)
                        .where(Alert.id == row.alert_id, Alert.tenant_id == tid, Alert.status == "new")
                        .values(status="resolved", resolved_at=now, updated_at=now)
                    )
                break
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such claimed action")
    await db.commit()
    return ActionResultResponse(recorded=True)


# ---- business email compromise searches --------------------------------------------------------------------------------------------------------------------
# An analyst starts a search on the Identities page (``identity_bec.py``); CORE collects it with the other queued actions, starts CIPP's BEC investigation and then reports how far it has got and,
# at the end, the finished report. Same path-token authentication as the routes above.


class BecProgress(BaseModel):
    step: int = Field(ge=0, le=1000)
    steps_total: int = Field(default=0, ge=0, le=1000)
    label: str | None = Field(default=None, max_length=300)


class BecResult(BaseModel):
    status: Literal["done", "failed"]
    message: str | None = Field(default=None, max_length=2000)
    report: dict[str, Any] | None = Field(default=None, description="CIPP's finished report, kept whole.")
    summary: dict[str, Any] = Field(default_factory=dict, description="What the page shows at a glance.")


class BecAck(BaseModel):
    recorded: bool


MAX_BEC_REPORT_BYTES = 3_000_000
MAX_BEC_SUMMARY_BYTES = 100_000  # what the page shows at a glance: a few facts, never a second copy of the report


async def _bec_case_for(db: Any, tenant_id: Any, case_id: uuid.UUID) -> Any:
    """The open case (pending or running) this token may answer, found in the owner's scope, or None. Runs ``acting_as_tenant`` for the case's own client on return via the second value."""
    from app.models.bec_case import BecCase  # noqa: PLC0415

    # ONE read inside the cross-tenant block, naming exactly the owner's scope: entering each client in turn cost four or more statements apiece on every progress call from CORE.
    scope = await _scope_ids(db, tenant_id)
    async with cross_tenant_reads(db):
        row = (await db.execute(select(BecCase).where(BecCase.id == case_id, BecCase.tenant_id.in_(scope)))).scalars().first()
    return (row, row.tenant_id) if row is not None else (None, None)


@router.post("/core-feed/{tenant_token}/bec/{case_id}/progress", response_model=BecAck)
async def report_bec_progress(tenant_token: str, case_id: uuid.UUID, body: BecProgress, db: DBSession) -> BecAck:
    """CORE says how far a BEC search has got. Only an open case of this tenant's scope can be updated."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    row, tid = await _bec_case_for(db, tenant_id, case_id)
    if row is None or row.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such open case")
    async with acting_as_tenant(db, tid):
        row.status = "running"
        row.step, row.steps_total, row.step_label = body.step, body.steps_total, body.label
        row.updated_at = datetime.now(UTC)
        await db.commit()
    return BecAck(recorded=True)


@router.post("/core-feed/{tenant_token}/bec/{case_id}/result", response_model=BecAck)
async def report_bec_result(tenant_token: str, case_id: uuid.UUID, body: BecResult, db: DBSession) -> BecAck:
    """CORE hands over the finished report (or says why there is none). Answered once: a finished case cannot be overwritten."""
    import json  # noqa: PLC0415

    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    if body.report is not None and len(json.dumps(body.report)) > MAX_BEC_REPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The report is too large")
    if len(json.dumps(body.summary)) > MAX_BEC_SUMMARY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The summary is too large")
    row, tid = await _bec_case_for(db, tenant_id, case_id)
    if row is None or row.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such open case")
    now = datetime.now(UTC)
    async with acting_as_tenant(db, tid):
        row.status = body.status
        row.message = body.message
        row.report = body.report
        row.summary = body.summary
        row.updated_at = row.finished_at = now
        if body.status == "done":
            # CIPP's own High or Medium rating becomes an alert for the client (one per search); a Low or missing rating raises none. Never raises: the report is kept whatever happens here.
            from app.services.bec_findings import finding_for_case  # noqa: PLC0415
            from app.services.identity_detections import save_findings  # noqa: PLC0415

            try:
                finding = finding_for_case(
                    case_ref=row.case_ref, case_id=str(row.id), email=row.email, summary=body.summary or {}, report=body.report, now=now
                )
                if finding is not None:
                    await save_findings(db, tid, [finding], now)
            except Exception:  # noqa: BLE001
                logger.warning("bec result: the alert could not be made for case=%s", row.id, exc_info=True)
        # The case and the ticket opened when the search was started get the result (the ticket only once its number is known).
        from app.services.bec_followup import on_result  # noqa: PLC0415

        await on_result(db, row, now)
        await db.commit()
    return BecAck(recorded=True)


class ScriptItem(BaseModel):
    id: int = Field(ge=1, le=2_000_000_000)
    name: str = Field(min_length=1, max_length=200)
    one_click: bool = Field(
        default=False, description="Whether CORE runs it at once when asked from A.C.O.R.N (otherwise CORE asks its owner first)."
    )


class ScriptsReport(BaseModel):
    scripts: list[ScriptItem] = Field(max_length=200)


class ScriptsResponse(BaseModel):
    stored: int


@router.post("/core-feed/{tenant_token}/scripts", response_model=ScriptsResponse)
async def report_core_feed_scripts(tenant_token: str, body: ScriptsReport, db: DBSession) -> ScriptsResponse:
    """CORE tells A.C.O.R.N which NinjaOne scripts its owner switched on, so an alert can offer them. The whole list replaces the last one (a script switched off disappears)."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    scripts = [s.model_dump() for s in body.scripts]
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(
            settings=func.jsonb_set(
                func.coalesce(Tenant.settings, cast({}, JSONB)), cast(["core_scripts"], ARRAY(Text)), cast(scripts, JSONB), True
            )
        )
    )
    await db.commit()
    return ScriptsResponse(stored=len(scripts))


class NinjaRoleItem(BaseModel):
    id: int = Field(ge=1, le=2_000_000_000)
    name: str = Field(min_length=1, max_length=200)
    node_class: str = Field(min_length=1, max_length=60)


class NinjaLocationItem(BaseModel):
    id: int = Field(ge=1, le=2_000_000_000)
    name: str = Field(min_length=1, max_length=200)


class NinjaOrgItem(BaseModel):
    id: int = Field(ge=1, le=2_000_000_000)
    name: str = Field(min_length=1, max_length=300)
    locations: list[NinjaLocationItem] = Field(max_length=100)


class NinjaDeployOptionsReport(BaseModel):
    roles: list[NinjaRoleItem] = Field(max_length=300)
    organizations: list[NinjaOrgItem] = Field(max_length=3000)


class NinjaDeployOptionsResponse(BaseModel):
    roles: int
    organizations: int


@router.post("/core-feed/{tenant_token}/ninja-deploy-options", response_model=NinjaDeployOptionsResponse)
async def report_core_feed_ninja_deploy_options(
    tenant_token: str, body: NinjaDeployOptionsReport, db: DBSession
) -> NinjaDeployOptionsResponse:
    """CORE tells A.C.O.R.N which NinjaOne roles, organizations and locations the Devices page can offer for installing the agent. The whole list replaces the last one."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    value = {"roles": [r.model_dump() for r in body.roles], "organizations": [o.model_dump() for o in body.organizations]}
    await db.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id)
        .values(
            settings=func.jsonb_set(
                func.coalesce(Tenant.settings, cast({}, JSONB)), cast(["ninja_deploy"], ARRAY(Text)), cast(value, JSONB), True
            )
        )
    )
    await db.commit()
    return NinjaDeployOptionsResponse(roles=len(body.roles), organizations=len(body.organizations))


class ClientItem(BaseModel):
    id: str = Field(min_length=1, max_length=200, description="The vendor's own id for the client.")
    name: str = Field(min_length=1, max_length=300)
    microsoft_tenant_id: str | None = Field(
        default=None,
        max_length=64,
        description="The Microsoft 365 tenant id the tool reports for the client, when it does: it links the client to the one another tool already mapped.",
    )


class ClientsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    clients: list[ClientItem] = Field(max_length=5000)


class ClientsResponse(BaseModel):
    new: int
    linked: int


@router.post("/core-feed/{tenant_token}/clients", response_model=ClientsResponse)
async def report_core_feed_clients(tenant_token: str, body: ClientsReport, db: DBSession) -> ClientsResponse:
    """CORE sends the list of clients one vendor has (Petra tenants, Halo clients, ...), so each can be mapped to an A.C.O.R.N tenant on the MSSP page."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    created, linked = await upsert_clients(
        db, tenant_id, body.vendor, [IncomingClient(c.id, c.name.strip(), c.microsoft_tenant_id) for c in body.clients if c.name.strip()]
    )
    await db.commit()
    return ClientsResponse(new=created, linked=linked)


class LinkedTicket(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    system: Literal["halopsa"] = "halopsa"
    summary: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=120)
    client: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=500, pattern=r"^https://")


class TicketsItem(BaseModel):
    uid: str = Field(min_length=1, max_length=200)
    tickets: list[LinkedTicket] = Field(max_length=20)


class TicketsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[TicketsItem] = Field(max_length=500)


class TicketsResponse(BaseModel):
    updated: int


async def apply_tickets(db: Any, tenant_id: Any, report: TicketsReport) -> int:
    """Store the PSA tickets linked to each incident on its alert (``enrichment_data.tickets``), in ``tenant_id``. The caller owns the transaction."""
    # A vendor's alert ids are "huntress:<id>" for an incident report but also "huntress-escalation:<id>" and "huntress-signal:<id>" for the other kinds of alert from the same tool.
    prefixes = (f"{report.vendor}:", f"{report.vendor}-")
    updated = 0
    uids: list[str] = []
    for item in report.items:
        if not item.uid.startswith(prefixes):
            continue
        value = {"tickets": [t.model_dump(exclude_none=True) for t in item.tickets]}
        same = (Alert.tenant_id == tenant_id, Alert.raw_event["finding"]["uid"].astext == item.uid)
        result = await db.execute(
            update(Alert).where(*same).values(enrichment_data=Alert.enrichment_data.op("||")(literal(value, type_=JSONB)))
        )
        updated += result.rowcount or 0
        uids.append(item.uid)
    if uids:
        # The last ticket closing closes an alert its tool has already closed (one statement for the whole report, not one per incident).
        now = datetime.now(UTC)
        await db.execute(
            update(Alert)
            .where(
                Alert.tenant_id == tenant_id,
                Alert.raw_event["finding"]["uid"].astext.in_(uids),
                Alert.status.notin_(FINISHED_ALERT_STATUSES),
                closed_in_tool(),
                tickets_all_closed(),
            )
            .values(
                status="resolved",
                resolved_at=now,
                updated_at=now,
                tags=Alert.tags.op("||")(literal([f"closed-in-{report.vendor}"], type_=JSONB)),
            )
        )
        # A closed ticket also resolves an alert its tool has NOT closed, when every ticket on it is closed and every other alert of its case is already finished (a case still open keeps it open).
        await db.execute(
            update(Alert)
            .where(
                Alert.tenant_id == tenant_id,
                Alert.raw_event["finding"]["uid"].astext.in_(uids),
                Alert.status.notin_(FINISHED_ALERT_STATUSES),
                ~closed_in_tool(),
                tickets_all_closed(),
                case_has_no_other_open_alert(),
            )
            .values(status="resolved", resolved_at=now, updated_at=now, tags=Alert.tags.op("||")(literal(["ticket-closed"], type_=JSONB)))
        )
    return updated


_HALO_BASE = re.compile(r"^(https://[a-z0-9][a-z0-9-]*\.halopsa\.com)/tickets\?id=", re.IGNORECASE)


def halo_base_from(report: TicketsReport) -> str | None:
    """The HaloPSA address (``https://acme.halopsa.com``) the tickets in this report link to, so a ticket someone enters by number alone can be given its link too. Only a HaloPSA address is kept."""
    for item in report.items:
        for t in item.tickets:
            m = _HALO_BASE.match(t.url or "")
            if m:
                return m.group(1).lower()
    return None


@router.post("/core-feed/{tenant_token}/tickets", response_model=TicketsResponse)
async def report_core_feed_tickets(tenant_token: str, body: TicketsReport, db: DBSession) -> TicketsResponse:
    """Record the PSA (HaloPSA) tickets linked to open vendor incidents, so each alert shows its tickets."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    halo = halo_base_from(body)
    if halo is not None:
        owner = await db.get(Tenant, tenant_id)
        if owner is not None and (owner.settings or {}).get("halopsa_base_url") != halo:
            owner.settings = {**(owner.settings or {}), "halopsa_base_url": halo}
    prefixes = (f"{body.vendor}:", f"{body.vendor}-")
    holders = await _tenants_holding(db, tenant_id, [i.uid for i in body.items if i.uid.startswith(prefixes)])
    held = dict(holders)
    updated = sum(
        await _across(
            db,
            tenant_id,
            lambda tid: apply_tickets(db, tid, body.model_copy(update={"items": [i for i in body.items if i.uid in held[tid]]})),
            tenants=[tid for tid, _ in holders],
        )
    )
    await db.commit()
    return TicketsResponse(updated=updated)


class RiskTicketsOut(BaseModel):
    tickets: list[str]


@router.get("/core-feed/{tenant_token}/risk-tickets", response_model=RiskTicketsOut)
async def core_feed_risk_tickets(tenant_token: str, db: DBSession) -> RiskTicketsOut:
    """The HaloPSA ticket numbers opened from Client Risk Score questions that CORE should read the status of (not closed, or closed only recently)."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    per_tenant = await _across(db, tenant_id, lambda tid: vcio_tickets.tracked_ticket_ids(db, tid, now))
    wanted: list[str] = []
    for ids in per_tenant:
        for t in ids:
            if t not in wanted:
                wanted.append(t)
    return RiskTicketsOut(tickets=wanted[: vcio_tickets.TRACKED_MAX])


class RiskTicketStatus(BaseModel):
    id: str = Field(pattern=r"^[0-9]{1,12}$")
    # HaloPSA's name for the ticket's status ("On Hold", "Waiting on Customer"...); none when CORE could not read one.
    status: str | None = Field(default=None, max_length=100)


class RiskTicketStatuses(BaseModel):
    tickets: list[RiskTicketStatus] = Field(max_length=500)


class RiskTicketStatusesOut(BaseModel):
    updated: int


@router.post("/core-feed/{tenant_token}/risk-tickets/status", response_model=RiskTicketStatusesOut)
async def report_core_feed_risk_ticket_statuses(tenant_token: str, body: RiskTicketStatuses, db: DBSession) -> RiskTicketStatusesOut:
    """Record the status CORE read from HaloPSA for the tickets opened from Client Risk Score questions, so each question's line shows where its ticket is."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    statuses = {t.id: t.status for t in body.tickets}
    updated = sum(await _across(db, tenant_id, lambda tid: vcio_tickets.apply_statuses(db, tid, statuses, now)))
    await db.commit()
    return RiskTicketStatusesOut(updated=updated)


class FinanceLineIn(BaseModel):
    item: str = Field(max_length=200)
    qty: float
    unit_price: float
    unit_cost: float


class FinanceRecurringIn(BaseModel):
    id: str = Field(default="", max_length=20)
    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(default="", max_length=200)
    # HaloPSA's own period code and next invoice date, kept as sent.
    period: int | None = None
    next: str | None = Field(default=None, max_length=40)
    lines: list[FinanceLineIn] = Field(max_length=300)


class FinanceInvoiceIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(default="", max_length=200)
    number: str = Field(default="", max_length=40)
    invoice_date: str | None = Field(default=None, max_length=40)
    due: str | None = Field(default=None, max_length=40)
    total: float
    amount_due: float


class FinanceSnapshotIn(BaseModel):
    recurring: list[FinanceRecurringIn] = Field(max_length=1000)
    invoices: list[FinanceInvoiceIn] = Field(max_length=10000)


class FinanceSnapshotOut(BaseModel):
    recurring: int
    invoices: int


@router.post("/core-feed/{tenant_token}/finance", response_model=FinanceSnapshotOut)
async def report_core_feed_finance(tenant_token: str, body: FinanceSnapshotIn, db: DBSession) -> FinanceSnapshotOut:
    """Keep the latest HaloPSA money snapshot CORE read (recurring invoices with their lines, invoices still owed). It replaces the one before; margin and ageing are worked out from it when a person with the finance permissions asks."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = (await db.execute(select(FinanceHaloSnapshot).where(FinanceHaloSnapshot.tenant_id == tenant_id))).scalar_one_or_none()
    payload = body.model_dump()
    if row is None:
        db.add(FinanceHaloSnapshot(tenant_id=tenant_id, payload=payload, received_at=now))
    else:
        row.payload, row.received_at = payload, now
    await db.commit()
    return FinanceSnapshotOut(recurring=len(body.recurring), invoices=len(body.invoices))


class ProfitInvoiceMonthIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(default="", max_length=200)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    revenue: float
    invoices: int = Field(ge=0, le=100000)


class ProfitHoursIn(BaseModel):
    client: str = Field(max_length=200)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    agent_id: str = Field(default="", max_length=20)
    charge_type: str = Field(default="", max_length=80)
    hours: float = Field(ge=0, le=100000)


class ProfitTicketIn(BaseModel):
    client: str = Field(max_length=200)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    ticket_id: str = Field(pattern=r"^[0-9]{1,12}$")
    summary: str = Field(default="", max_length=200)
    hours: float = Field(ge=0, le=100000)
    entries: int = Field(default=1, ge=0, le=100000)
    agent_ids: list[str] = Field(default_factory=list, max_length=10)


class ProfitAgentIn(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    name: str = Field(max_length=200)
    team: str = Field(default="", max_length=80)
    active: bool = True
    charge_rate: float | None = None


class ProfitSnapshotIn(BaseModel):
    months: list[str] = Field(max_length=24)
    invoices: list[ProfitInvoiceMonthIn] = Field(max_length=20000)
    hours: list[ProfitHoursIn] = Field(max_length=250000)
    # The tickets the hours went on (the most-worked per client and month). Absent from an older CORE: the breakdown then says they are not sent yet.
    tickets: list[ProfitTicketIn] | None = Field(default=None, max_length=40000)
    agents: list[ProfitAgentIn] = Field(max_length=500)


class ProfitSnapshotOut(BaseModel):
    invoices: int
    hours: int
    agents: int


BOOKS_CATEGORIES = ("payroll_cogs", "addon_software", "support_software", "travel", "equipment", "hardware", "sales_marketing", "overhead")
BOOKS_AMOUNT = {"ge": -100_000_000, "le": 100_000_000}


class BooksMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    payroll_cogs: float = Field(default=0, **BOOKS_AMOUNT)
    addon_software: float = Field(default=0, **BOOKS_AMOUNT)
    support_software: float = Field(default=0, **BOOKS_AMOUNT)
    travel: float = Field(default=0, **BOOKS_AMOUNT)
    equipment: float = Field(default=0, **BOOKS_AMOUNT)
    hardware: float = Field(default=0, **BOOKS_AMOUNT)
    sales_marketing: float = Field(default=0, **BOOKS_AMOUNT)
    overhead: float = Field(default=0, **BOOKS_AMOUNT)


class BooksIn(BaseModel):
    months: list[BooksMonthIn] = Field(max_length=36)
    unmapped: list[str] = Field(default_factory=list, max_length=50)


class BooksOut(BaseModel):
    months: int
    entries: int


@router.post("/core-feed/{tenant_token}/books", response_model=BooksOut)
async def report_core_feed_books(tenant_token: str, body: BooksIn, db: DBSession) -> BooksOut:
    """Keep the company-wide cost per month CORE read from QuickBooks' profit and loss, as the cost entries of the Net income page (source ``quickbooks``). For each month sent the earlier QuickBooks entries are replaced,
    so a correction in the books reaches the page; a typed (``manual``) company-wide entry for the same month and category stays on file but the QuickBooks figure is the one used. Months not sent are left as they were."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    months = sorted({m.month for m in body.months})
    if months:
        await db.execute(delete(FinanceCostEntry).where(FinanceCostEntry.tenant_id == tenant_id, FinanceCostEntry.source == "quickbooks", FinanceCostEntry.month.in_(months)))
    entries = 0
    for m in {m.month: m for m in body.months}.values():
        for category in BOOKS_CATEGORIES:
            amount = Decimal(str(round(getattr(m, category), 2)))
            if amount == 0:
                continue
            db.add(
                FinanceCostEntry(
                    tenant_id=tenant_id,
                    month=m.month,
                    category=category,
                    client_key="",
                    client_name="",
                    source="quickbooks",
                    amount=amount,
                    note="From QuickBooks",
                    updated_by=None,
                    updated_at=now,
                )
            )
            entries += 1
    await db.commit()
    return BooksOut(months=len(months), entries=entries)


class VendorCostRowIn(BaseModel):
    account: Literal["5100", "5500"]
    vendor: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=-100_000_000, le=100_000_000)


class VendorCostMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    rows: list[VendorCostRowIn] = Field(max_length=400)


class VendorCostsIn(BaseModel):
    months: list[VendorCostMonthIn] = Field(max_length=36)


class VendorCostsOut(BaseModel):
    months: int
    rows: int


@router.post("/core-feed/{tenant_token}/vendor-costs", response_model=VendorCostsOut)
async def report_core_feed_vendor_costs(tenant_token: str, body: VendorCostsIn, db: DBSession) -> VendorCostsOut:
    """Keep what each software vendor billed per month, as QuickBooks booked it (the add-on and the support and maintenance software accounts). A month sent again is replaced; months not sent are left as they were. Net income carries each vendor's bill to the clients that use it."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    months = sorted({m.month for m in body.months})
    if months:
        await db.execute(delete(FinanceVendorCost).where(FinanceVendorCost.tenant_id == tenant_id, FinanceVendorCost.month.in_(months)))
    total = 0
    for m in {m.month: m for m in body.months}.values():
        merged: dict[tuple[str, str], Decimal] = {}
        for r in m.rows:
            key = (r.account, " ".join(r.vendor.split()))
            merged[key] = merged.get(key, Decimal(0)) + Decimal(str(round(r.amount, 2)))
        for (account, vendor), amount in merged.items():
            if amount != 0:
                db.add(FinanceVendorCost(tenant_id=tenant_id, month=m.month, account=account, vendor=vendor, amount=amount, received_at=now))
                total += 1
    await db.commit()
    return VendorCostsOut(months=len(months), rows=total)


class PnlLineIn(BaseModel):
    depth: int = Field(ge=0, le=8)
    kind: Literal["header", "line", "total"]
    label: str = Field(min_length=1, max_length=200)
    amount: float | None = Field(default=None, ge=-100_000_000_000, le=100_000_000_000)


class PnlMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    lines: list[PnlLineIn] = Field(max_length=600)


class PnlIn(BaseModel):
    months: list[PnlMonthIn] = Field(max_length=36)


class PnlOut(BaseModel):
    months: int
    lines: int


@router.post("/core-feed/{tenant_token}/pnl", response_model=PnlOut)
async def report_core_feed_pnl(tenant_token: str, body: PnlIn, db: DBSession) -> PnlOut:
    """Keep QuickBooks' profit and loss as it reads, line by line, for each month sent (accrual basis). A month sent again is replaced; months not sent are left as they were. Read only by people with the finance permissions."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    by_month = {m.month: m for m in body.months}
    if by_month:
        await db.execute(delete(FinancePnlMonth).where(FinancePnlMonth.tenant_id == tenant_id, FinancePnlMonth.month.in_(list(by_month))))
    total = 0
    for month, m in by_month.items():
        lines = [{"depth": ln.depth, "kind": ln.kind, "label": " ".join(ln.label.split()), "amount": None if ln.amount is None else round(ln.amount, 2)} for ln in m.lines]
        db.add(FinancePnlMonth(tenant_id=tenant_id, month=month, payload=lines, received_at=now))
        total += len(lines)
    await db.commit()
    return PnlOut(months=len(by_month), lines=total)


class CostTransactionIn(BaseModel):
    account: Literal["5600", "5800", "5805"]
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    type: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=120)
    customer: str = Field(default="", max_length=200)
    memo: str = Field(default="", max_length=300)
    split: str = Field(default="", max_length=120)
    amount: float = Field(ge=-100_000_000_000, le=100_000_000_000)


class CostTransactionsMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    rows: list[CostTransactionIn] = Field(max_length=5000)


class CostTransactionsIn(BaseModel):
    months: list[CostTransactionsMonthIn] = Field(max_length=36)


class CostTransactionsOut(BaseModel):
    months: int
    rows: int


@router.post("/core-feed/{tenant_token}/cost-transactions", response_model=CostTransactionsOut)
async def report_core_feed_cost_transactions(tenant_token: str, body: CostTransactionsIn, db: DBSession) -> CostTransactionsOut:
    """Keep the transactions behind the travel and hardware costs per month, as QuickBooks booked them. A month sent again is replaced; months not sent are left as they were. Read only by people with the finance permissions."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    by_month = {m.month: m for m in body.months}
    if by_month:
        await db.execute(delete(FinanceCostTransactions).where(FinanceCostTransactions.tenant_id == tenant_id, FinanceCostTransactions.month.in_(list(by_month))))
    total = 0
    for month, m in by_month.items():
        rows = [
            {"account": r.account, "date": r.date, "type": r.type, "name": r.name, "customer": r.customer, "memo": r.memo, "split": r.split, "amount": round(r.amount, 2)}
            for r in m.rows
            if r.date[:7] == month and round(r.amount, 2) != 0
        ]
        db.add(FinanceCostTransactions(tenant_id=tenant_id, month=month, payload=rows, received_at=now))
        total += len(rows)
    await db.commit()
    return CostTransactionsOut(months=len(by_month), rows=total)


class QboCustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=-100_000_000_000, le=100_000_000_000)


class QboSalesMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    customers: list[QboCustomerIn] = Field(max_length=3000)


class QboSalesIn(BaseModel):
    months: list[QboSalesMonthIn] = Field(max_length=36)


class QboSalesOut(BaseModel):
    months: int
    customers: int


@router.post("/core-feed/{tenant_token}/qbo-sales", response_model=QboSalesOut)
async def report_core_feed_qbo_sales(tenant_token: str, body: QboSalesIn, db: DBSession) -> QboSalesOut:
    """Keep what each QuickBooks customer was invoiced per month (sales by customer, accrual basis). A month sent again is replaced; months not sent are left as they were. Read only by people with the finance permissions."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    by_month = {m.month: m for m in body.months}
    if by_month:
        await db.execute(delete(FinanceQboSales).where(FinanceQboSales.tenant_id == tenant_id, FinanceQboSales.month.in_(list(by_month))))
    total = 0
    for month, m in by_month.items():
        merged: dict[str, float] = {}
        for c in m.customers:
            name = " ".join(c.name.split())
            merged[name] = merged.get(name, 0.0) + c.amount
        rows = [{"name": n, "amount": round(a, 2)} for n, a in sorted(merged.items()) if round(a, 2) != 0]
        db.add(FinanceQboSales(tenant_id=tenant_id, month=month, payload=rows, received_at=now))
        total += len(rows)
    await db.commit()
    return QboSalesOut(months=len(by_month), customers=total)


class ProfitTicketsIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    tickets: list[ProfitTicketIn] = Field(max_length=100000)


class ProfitTicketsOut(BaseModel):
    month: str
    tickets: int


@router.post("/core-feed/{tenant_token}/profit-tickets", response_model=ProfitTicketsOut)
async def report_core_feed_profit_tickets(tenant_token: str, body: ProfitTicketsIn, db: DBSession) -> ProfitTicketsOut:
    """Keep every ticket a client's hours went on in one month, as CORE read them from HaloPSA's time entries. Sending a month again replaces that month's list; other months are untouched. The Profitability client detail lists them."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    payload = [t.model_dump() for t in body.tickets]
    row = (await db.execute(select(FinanceProfitTickets).where(FinanceProfitTickets.tenant_id == tenant_id, FinanceProfitTickets.month == body.month))).scalar_one_or_none()
    if row is None:
        db.add(FinanceProfitTickets(tenant_id=tenant_id, month=body.month, payload=payload, received_at=now))
    else:
        row.payload, row.received_at = payload, now
    await db.commit()
    return ProfitTicketsOut(month=body.month, tickets=len(payload))


@router.post("/core-feed/{tenant_token}/profitability", response_model=ProfitSnapshotOut)
async def report_core_feed_profitability(tenant_token: str, body: ProfitSnapshotIn, db: DBSession) -> ProfitSnapshotOut:
    """Keep the latest HaloPSA profitability summary CORE read (invoiced revenue per client per month, hours per client, the agents). It replaces the one before; profit is worked out when a person with the finance permissions asks."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == tenant_id))).scalar_one_or_none()
    payload = body.model_dump()
    if row is None:
        db.add(FinanceProfitSnapshot(tenant_id=tenant_id, payload=payload, received_at=now))
    else:
        row.payload, row.received_at = payload, now
    await db.commit()
    return ProfitSnapshotOut(invoices=len(body.invoices), hours=len(body.hours), agents=len(body.agents))


class TicketMonthIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(default="", max_length=200)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    created: int = Field(ge=0, le=1000000)
    resolved: int = Field(ge=0, le=1000000)
    responded: int = Field(ge=0, le=1000000)
    response_minutes: float = Field(ge=0)
    created_by_type: dict[str, int] = Field(default_factory=dict, max_length=100)
    resolved_by_agent: dict[str, int] = Field(default_factory=dict, max_length=300)
    critical: int = Field(ge=0, le=1000000)
    high: int = Field(ge=0, le=1000000)


class TicketOpenIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(default="", max_length=200)
    total: int = Field(ge=0, le=1000000)
    critical: int = Field(ge=0, le=1000000)
    high: int = Field(ge=0, le=1000000)


class TicketStatsIn(BaseModel):
    months: list[str] = Field(max_length=40)
    rows: list[TicketMonthIn] = Field(max_length=60000)
    open_now: list[TicketOpenIn] = Field(max_length=5000)


class TicketStatsOut(BaseModel):
    rows: int
    open_clients: int


@router.post("/core-feed/{tenant_token}/ticket-stats", response_model=TicketStatsOut)
async def report_core_feed_ticket_stats(tenant_token: str, body: TicketStatsIn, db: DBSession) -> TicketStatsOut:
    """Keep the latest HaloPSA ticket statistics CORE read (per client per month, and what is open now). They replace the ones before; averages are worked out when a person asks."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == tenant_id))).scalar_one_or_none()
    payload = body.model_dump()
    if row is None:
        db.add(TicketStatsSnapshot(tenant_id=tenant_id, payload=payload, received_at=now))
    else:
        row.payload, row.received_at = payload, now
    await db.commit()
    return TicketStatsOut(rows=len(body.rows), open_clients=len(body.open_now))


class CsatMonthIn(BaseModel):
    company: str = Field(max_length=200)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    positive: int = Field(ge=0, le=1000000)
    neutral: int = Field(ge=0, le=1000000)
    negative: int = Field(ge=0, le=1000000)
    total: int = Field(ge=0, le=1000000)


class CsatRecentIn(BaseModel):
    company: str = Field(max_length=200)
    date: str = Field(max_length=30)
    contact: str = Field(default="", max_length=120)
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    rating: str = Field(default="", max_length=80)
    comment: str = Field(default="", max_length=400)
    ticket_id: str = Field(default="", max_length=40)


class CsatIn(BaseModel):
    months: list[str] = Field(max_length=24)
    rows: list[CsatMonthIn] = Field(max_length=20000)
    recent: list[CsatRecentIn] = Field(max_length=5000)


class CsatOut(BaseModel):
    rows: int
    recent: int


@router.post("/core-feed/{tenant_token}/csat", response_model=CsatOut)
async def report_core_feed_csat(tenant_token: str, body: CsatIn, db: DBSession) -> CsatOut:
    """Keep the latest SimpleSat customer satisfaction summary CORE read (per company per month, and each company's newest comments). It replaces the one before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = (await db.execute(select(CsatSnapshot).where(CsatSnapshot.tenant_id == tenant_id))).scalar_one_or_none()
    payload = body.model_dump()
    if row is None:
        db.add(CsatSnapshot(tenant_id=tenant_id, payload=payload, received_at=now))
    else:
        row.payload, row.received_at = payload, now
    await db.commit()
    return CsatOut(rows=len(body.rows), recent=len(body.recent))


class DeviceItem(BaseModel):
    uid: str = Field(min_length=1, max_length=200)
    hostname: str = Field(min_length=1, max_length=255)


class DevicesReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[DeviceItem] = Field(max_length=500)


class DevicesResponse(BaseModel):
    updated: int


async def apply_devices(db: Any, tenant_id: Any, report: DevicesReport) -> int:
    """Name the device on stored alerts that have none (``affected_hosts``), in ``tenant_id``. Only an EMPTY host list is filled: what ingestion already set is never overwritten, and nothing is re-scored.
    The caller owns the transaction."""
    prefix = f"{report.vendor}:"
    updated = 0
    for item in report.items:
        host = item.hostname.strip()
        if not host or not item.uid.startswith(prefix):
            continue
        result = await db.execute(
            update(Alert)
            .where(
                Alert.tenant_id == tenant_id,
                Alert.raw_event["finding"]["uid"].astext == item.uid,
                func.jsonb_array_length(func.coalesce(Alert.affected_hosts, literal([], type_=JSONB))) == 0,
            )
            .values(affected_hosts=literal([host], type_=JSONB))
        )
        updated += result.rowcount or 0
    return updated


@router.post("/core-feed/{tenant_token}/device-names", response_model=DevicesResponse)
async def report_core_feed_devices(tenant_token: str, body: DevicesReport, db: DBSession) -> DevicesResponse:
    """Record the device a vendor's incidents were raised on, for stored alerts that were forwarded without one (a Huntress incident names only its agent)."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    prefix = f"{body.vendor}:"
    holders = await _tenants_holding(db, tenant_id, [i.uid for i in body.items if i.uid.startswith(prefix)])
    held = dict(holders)
    updated = sum(
        await _across(
            db,
            tenant_id,
            lambda tid: apply_devices(db, tid, body.model_copy(update={"items": [i for i in body.items if i.uid in held[tid]]})),
            tenants=[tid for tid, _ in holders],
        )
    )
    await db.commit()
    return DevicesResponse(updated=updated)


ALERT_LINK_KEYS = ("device_url", "user_url")


class EntityItem(BaseModel):
    uid: str = Field(min_length=1, max_length=200)
    hostname: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    src_ip: str | None = Field(default=None, max_length=64)
    # A link to the alert in the vendor's own tool. Only a plain https address; it is set only where the alert has no link yet.
    url: str | None = Field(default=None, max_length=1000, pattern=r"^https://[^\s]+$")
    # Links to the device and the user in the vendor's tool (keys ``device_url`` and ``user_url``), https only. Set only where the alert has no links yet.
    links: dict[str, str] | None = None

    @field_validator("links")
    @classmethod
    def _links_are_safe(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        clean = {
            k: v
            for k, v in value.items()
            if k in ALERT_LINK_KEYS and isinstance(v, str) and len(v) <= 1000 and re.match(r"^https://[^\s]+$", v)
        }
        return clean or None


class EntitiesReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[EntityItem] = Field(max_length=500)


async def apply_entities(db: Any, tenant_id: Any, report: EntitiesReport) -> int:
    """Give stored alerts the host, user and address a vendor's evidence names, and a link to the alert in the vendor's tool, in ``tenant_id``. Each is filled only where it is EMPTY: what ingestion
    already set is never overwritten, and nothing is re-scored. Returns how many alert fields were filled. The caller owns the transaction."""
    # A vendor's alert ids start with its name and a colon (``huntress:123``) or, for a second kind of alert from the same tool, its name and a dash (``huntress-escalation:123``).
    prefixes = (f"{report.vendor}:", f"{report.vendor}-")
    filled = 0
    for item in report.items:
        if not item.uid.startswith(prefixes):
            continue
        for column, value in (
            (Alert.affected_hosts, item.hostname),
            (Alert.affected_users, item.username),
            (Alert.affected_ips, item.src_ip),
        ):
            cleaned = (value or "").strip()
            if not cleaned:
                continue
            result = await db.execute(
                update(Alert)
                .where(
                    Alert.tenant_id == tenant_id,
                    Alert.raw_event["finding"]["uid"].astext == item.uid,
                    func.jsonb_array_length(func.coalesce(column, literal([], type_=JSONB))) == 0,
                )
                .values({column.key: literal([cleaned], type_=JSONB)})
            )
            filled += result.rowcount or 0
        if item.url:
            result = await db.execute(
                update(Alert)
                .where(
                    Alert.tenant_id == tenant_id,
                    Alert.raw_event["finding"]["uid"].astext == item.uid,
                    Alert.raw_event["url"].astext.is_(None),
                )
                .values(raw_event=Alert.raw_event.op("||")(literal({"url": item.url}, type_=JSONB)))
            )
            filled += result.rowcount or 0
        if item.links:
            result = await db.execute(
                update(Alert)
                .where(
                    Alert.tenant_id == tenant_id,
                    Alert.raw_event["finding"]["uid"].astext == item.uid,
                    Alert.raw_event["links"].astext.is_(None),
                )
                .values(raw_event=Alert.raw_event.op("||")(literal({"links": item.links}, type_=JSONB)))
            )
            filled += result.rowcount or 0
    return filled


@router.post("/core-feed/{tenant_token}/entities", response_model=DevicesResponse)
async def report_core_feed_entities(tenant_token: str, body: EntitiesReport, db: DBSession) -> DevicesResponse:
    """Record the user, host and address a vendor's evidence names, for stored alerts that were forwarded without them (a Blumira finding carries none; its evidence does)."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, tenant_id)
    prefix = f"{body.vendor}:"
    holders = await _tenants_holding(db, tenant_id, [i.uid for i in body.items if i.uid.startswith(prefix)])
    held = dict(holders)
    filled = sum(
        await _across(
            db,
            tenant_id,
            lambda tid: apply_entities(db, tid, body.model_copy(update={"items": [i for i in body.items if i.uid in held[tid]]})),
            tenants=[tid for tid, _ in holders],
        )
    )
    await db.commit()
    return DevicesResponse(updated=filled)


class MetricDatasetIn(BaseModel):
    """One Metrics dataset as CORE sends it: the facts under ``data`` (lists of rows and the periods they cover; the shape of each key is described in app/services/metrics_*.py)."""

    data: dict[str, Any]


class MetricDatasetOut(BaseModel):
    key: str
    rows: int


_MAX_DATASET_ROWS = 300000


async def _keep_metric_dataset(db: Any, tenant_id: Any, key: str, body: MetricDatasetIn) -> MetricDatasetOut:
    """Keep the latest facts CORE read for one Metrics dataset. They replace the ones before; the pages are worked out when a person asks."""
    if key not in DATASET_KEYS:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    rows = sum(len(v) for v in body.data.values() if isinstance(v, list))
    if rows > _MAX_DATASET_ROWS:
        raise HTTPException(status_code=413, detail="That dataset is too large")
    await adopt_tenant(db, tenant_id)
    now = datetime.now(UTC)
    row = (
        await db.execute(select(MetricDataset).where(MetricDataset.tenant_id == tenant_id, MetricDataset.key == key))
    ).scalar_one_or_none()
    if row is None:
        db.add(MetricDataset(tenant_id=tenant_id, key=key, payload=body.data, received_at=now))
    else:
        row.payload, row.received_at = merge_dataset(key, row.payload, body.data), now
    await db.commit()
    return MetricDatasetOut(key=key, rows=rows)


@router.post("/core-feed/{tenant_token}/metric-staff-weekly", response_model=MetricDatasetOut)
async def report_core_feed_metric_staff_weekly(tenant_token: str, body: MetricDatasetIn, db: DBSession) -> MetricDatasetOut:
    """CORE's weekly facts per engineer (team, hours, utilization, days off, tickets closed and updated, calls, survey scores): replaces the ones before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    return await _keep_metric_dataset(db, tenant_id, "staff-weekly", body)


@router.post("/core-feed/{tenant_token}/metric-ticket-detail", response_model=MetricDatasetOut)
async def report_core_feed_metric_ticket_detail(tenant_token: str, body: MetricDatasetIn, db: DBSession) -> MetricDatasetOut:
    """CORE's weekly ticket facts (created and resolved by client, type, category and priority, resolution time, stale tickets): replaces the ones before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    return await _keep_metric_dataset(db, tenant_id, "ticket-detail", body)


@router.post("/core-feed/{tenant_token}/metric-invoice-lines", response_model=MetricDatasetOut)
async def report_core_feed_metric_invoice_lines(tenant_token: str, body: MetricDatasetIn, db: DBSession) -> MetricDatasetOut:
    """CORE's invoiced amounts per client per month per invoice line and billing category: replaces the ones before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    return await _keep_metric_dataset(db, tenant_id, "invoice-lines", body)


@router.post("/core-feed/{tenant_token}/metric-dialpad-weekly", response_model=MetricDatasetOut)
async def report_core_feed_metric_dialpad_weekly(tenant_token: str, body: MetricDatasetIn, db: DBSession) -> MetricDatasetOut:
    """CORE's Dialpad call counts and call time per engineer per week: replaces the ones before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    return await _keep_metric_dataset(db, tenant_id, "dialpad-weekly", body)


@router.post("/core-feed/{tenant_token}/metric-m365-roles", response_model=MetricDatasetOut)
async def report_core_feed_metric_m365_roles(tenant_token: str, body: MetricDatasetIn, db: DBSession) -> MetricDatasetOut:
    """CORE's Microsoft 365 directory roles and their members per client: replaces the ones before."""
    tenant_id = await _verify_core_feed_token(db, tenant_token)
    return await _keep_metric_dataset(db, tenant_id, "m365-roles", body)
