"""Alert management endpoints."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Text, and_, cast, false, func, not_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls import TenantDBSession
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.models.alert import Alert
from app.models.tenant import Tenant, User
from app.services import alert_other_clients, alert_outcomes
from app.services.alert_queue import (
    AlertAlreadyClaimedError,
    AlertNotFoundError,
    QueueResponse,
    build_queue,
    claim_alert,
)
from app.services.alert_rail import (
    MiniTimelineEvent,
    RecommendedAction,
    RelatedEntity,
    build_rail_envelope,
)
from app.services.alert_scope import alert_scope
from app.services.alert_status import FINISHED_ALERT_STATUSES, is_finished
from app.services.audit import emit_audit
from app.services.event_sanitiser import (
    SubmitPayloadTooLarge,
    sanitise_event_batch,
)
from app.services.narrative_loader import build_narrative
from app.services.narrative_projection import project_alert_to_narrative_inputs
from app.services.source_labels import narrative_names_the_inbox
from app.services.timestamp_bounds import coerce_with_bounds, now_utc
from app.services.timeutil import as_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])

# ─── idempotency-key validation ─────────────────────────────────────────────
# Per RFC draft "The Idempotency-Key HTTP Header Field", clients pick an
# opaque key. We restrict the alphabet so the key can be stored as TEXT
# without breaking the DB column (128 chars, ASCII-safe, no whitespace).
# Anything else is a 400 — better to reject early than mint a partial
# row that can't be looked up on retry.
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")


def _log_safe(value: str | None) -> str | None:
    """Strip CR/LF from a user-supplied string before it enters a log record.

    The idempotency key and ``connector_type`` are validated upstream
    (regex / Pydantic) and cannot in practice contain newlines, but static
    analysis (CodeQL ``py/log-injection``) does not recognise the regex as
    a sanitiser. This helper makes the cleansing explicit so the taint
    tracker treats the value as safe, while remaining a no-op for any
    well-formed input.
    """
    if value is None:
        return None
    return value.replace("\r", "").replace("\n", " ")


class AlertResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    description: str | None
    severity: str
    status: str
    priority: int
    category: str | None
    mitre_tactics: list
    mitre_techniques: list
    connector_type: str | None
    ai_score: float | None
    ai_summary: str | None
    ai_recommendations: list
    # Fusion confidence (W3). `confidence` is an integer 0-100; the band is
    # carried in `confidence_label` (high/medium/low) and the contributing
    # factors in `confidence_rationale`. All three can be NULL for legacy
    # alerts created before the fusion service emitted confidence.
    confidence: int | None = None
    confidence_label: str | None = None
    confidence_rationale: list | None = None
    disposition: str | None = None
    affected_ips: list
    affected_hosts: list
    affected_users: list
    case_id: uuid.UUID | None
    tags: list
    event_time: datetime
    first_seen: datetime
    last_seen: datetime
    snoozed_until: datetime | None = None
    snoozed_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Set by the list when the alert belongs to one of the caller's client tenants (an MSSP parent's view).
    client_name: str | None = None
    # Set only when the list is grouped (``collapse``): how many alerts share this one's rule and machine/user, this one included. 1 means it has no repeats.
    repeat_count: int | None = None
    # The tool CORE says the alert came from (raw_event.source: huntress, petra, ninjaone...). connector_type is just the generic JSON inbox for all of them.
    source: str | None = None
    # A link to this alert in the tool that raised it (Blumira finding, Petra incident, Field Effect alert), when the tool sent one: only a plain https address.
    source_url: str | None = None
    # Links to the device and the user in the tool that raised the alert (``device_url``, ``user_url``), when the tool's data allowed them: only plain https addresses.
    links: dict[str, str] = {}

    model_config = {"from_attributes": True}


class AlertDetailResponse(AlertResponse):
    """Alert response enriched with everything the Investigation Rail needs.

    The list endpoint stays on the smaller :class:`AlertResponse` shape
    to keep paginated payloads light. The detail endpoint promotes to
    this enriched shape so the rail renders without extra round-trips:

    * ``narrative`` — deterministic correlation prose. Cached on the
      ``Alert`` row by the fusion service; lazily filled by the
      endpoint when missing (legacy rows). Always a string by the
      time it leaves the API.
    * ``related_entities`` — pivotable entities grouped by
      principal / network / workflow / tenant.
    * ``mini_timeline`` — up to ``MAX_TIMELINE_EVENTS`` recent events
      merged from the case timeline and the audit log.
    * ``recommended_actions`` — normalised structured actions from
      the ResponderAgent (or the legacy list-of-strings shape).
    """

    narrative: str | None = None
    # The event as the source sent it (already redacted before storage). The alert page's Raw tab reads this; without it the tab always said "not available".
    raw_event: dict = {}
    related_entities: list[RelatedEntity] = []
    mini_timeline: list[MiniTimelineEvent] = []
    recommended_actions: list[RecommendedAction] = []


class AlertSnoozeRequest(BaseModel):
    """Snooze an alert from the mobile responder PWA."""

    duration_minutes: int | None = None
    until: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


async def tenants_holding_alerts(db: Any, scope: list[uuid.UUID]) -> set[uuid.UUID] | None:
    """The tenants of ``scope`` that hold at least one alert, from ONE grouped read instead of entering each tenant in turn (an MSSP has over two hundred clients, most with nothing: entering each took seven
    seconds). A tenant with no alerts adds nothing to a list or a tally, so skipping it changes no result. None when this cannot be read, so the caller goes through every tenant as before."""
    try:
        async with cross_tenant_reads(db):
            rows = (await db.execute(select(Alert.tenant_id).where(Alert.tenant_id.in_(scope)).group_by(Alert.tenant_id))).all()
    except Exception:  # noqa: BLE001 - a speed-up must never be the reason a list fails
        logger.warning("alerts.tenants_holding_alerts_unavailable", exc_info=True)
        return None
    return {r[0] for r in rows}


def _tool_of(alert: Alert) -> str | None:
    raw = alert.raw_event if isinstance(alert.raw_event, dict) else {}
    value = raw.get("source")
    return value if isinstance(value, str) and value else None


class AlertSummary(BaseModel):
    """The tally above the alerts list: counts over the whole scope (own + clients, or the one client chosen), ignoring the severity / status filters."""

    total: int
    critical: int
    high: int
    unresolved: int
    # Open alerts (not resolved, closed or a false positive) that no HaloPSA ticket is linked to, found by CORE or entered by hand.
    no_ticket: int = 0


def _ticket_list_text(name: str) -> Any:
    return Alert.enrichment_data[name].as_string()


def has_ticket_expr() -> Any:
    """SQL condition: the alert has at least one linked HaloPSA ticket (``enrichment_data.tickets``, from CORE) or manual ticket (``enrichment_data.manual_tickets``)."""
    conditions = []
    for key in ("tickets", "manual_tickets"):
        text_of = _ticket_list_text(key)
        conditions.append(and_(text_of.is_not(None), text_of.not_in(["[]", "null", ""])))
    return or_(*conditions)


# ``status=open`` on the list means every alert that is not finished (resolved, closed or a false positive): the console's "Open all" tab.
OPEN_STATUS = "open"
FINISHED_STATUSES = FINISHED_ALERT_STATUSES
_UNRESOLVED = {"new", "triaging", "in_progress", "investigating"}


class AlertListResponse(BaseModel):
    summary: AlertSummary | None = None
    items: list[AlertResponse]
    total: int
    page: int
    page_size: int
    pages: int


# The statuses an analyst can set by hand. "suppressed" is set only by a suppression rule (it remembers the status it replaced), so it is not here.
SETTABLE_STATUSES = ("new", "triaged", "triaging", "investigating", "in_progress", "resolved", "closed", "false_positive", "fp")
MAX_TAGS = 50
MAX_TAG_LENGTH = 64


class AlertUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=30)
    priority: int | None = Field(default=None, ge=0, le=100)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    assigned_to_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in SETTABLE_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(SETTABLE_STATUSES)}")
        return v

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for tag in v:
            tag = " ".join(str(tag).split())
            if not tag or len(tag) > MAX_TAG_LENGTH:
                raise ValueError(f"each tag must be 1 to {MAX_TAG_LENGTH} characters")
            if tag not in out:
                out.append(tag)
        return out


class AlertStatsResponse(BaseModel):
    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    new_last_24h: int
    critical_open: int


class AlertSubmitRequest(BaseModel):
    """Direct-write alert submission payload.

    The founder-flow demo (`aisoc submit <file>`) and any operator who wants
    to land a hand-crafted alert on the local dev stack without a connector
    POST one of these. The body intentionally mirrors the ingest envelope
    used by real connectors so the same fixture works against either path:

        { connector_id, connector_type, source_format, events: [...] }

    The single payload synthesises one ``Alert`` row, written directly into
    the tenant's database, so the result is visible in
    ``GET /api/v1/alerts`` and the web console within the same second.
    This deliberately bypasses the Kafka detection/correlation pipeline
    (which fresh clones don't run by default) so the documented "alert in
    seconds" promise in the quickstart actually holds.
    """

    events: list[dict] = []
    connector_id: str | None = None
    connector_type: str | None = None
    source_format: str | None = None
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    tags: list[str] | None = None


# Map vendor-native severity strings to the canonical A.C.O.R.N severity ladder.
# Keep this in sync with the five-tier ladder documented in AGENTS.md
# (info | low | medium | high | critical).
_SEVERITY_MAP = {
    "info": "info",
    "informational": "info",
    "debug": "info",
    "low": "low",
    "minor": "low",
    "warning": "low",
    "medium": "medium",
    "moderate": "medium",
    "warn": "medium",
    "high": "high",
    "error": "high",
    "major": "high",
    "critical": "critical",
    "crit": "critical",
    "severe": "critical",
    "fatal": "critical",
    "emergency": "critical",
}
_SEVERITY_PRIORITY = {
    "info": 10,
    "low": 30,
    "medium": 50,
    "high": 75,
    "critical": 95,
}


def _normalize_severity(raw: str | None) -> str:
    if not raw:
        return "medium"
    return _SEVERITY_MAP.get(raw.strip().lower(), "medium")


def _max_severity(values: list[str]) -> str:
    """Pick the highest severity from a list using the canonical ladder."""
    ladder = ["info", "low", "medium", "high", "critical"]
    best = "info"
    for v in values:
        if ladder.index(v) > ladder.index(best):
            best = v
    return best


def _coerce_published(event: dict, now: datetime | None = None) -> tuple[datetime | None, bool]:
    """Extract a bounded event timestamp from an OCSF / Okta-shaped dict.

    Thin wrapper around :func:`app.services.timestamp_bounds.coerce_with_bounds`
    that gives the rest of this module a stable, locally-named helper. The
    underlying function scans the canonical timestamp fields
    (``published`` / ``time`` / ``@timestamp`` / ``timestamp`` / ``eventTime``),
    parses strings, ``datetime`` objects, and Unix epochs (seconds **or**
    milliseconds), and clamps out-of-window values to the configured
    ``MIN_AGE`` / ``MAX_FUTURE`` window so a broken connector can't poison
    SLA timers with a 1970 or 2099 timestamp.

    Returns ``(datetime | None, was_clamped)`` — ``was_clamped`` is ``True``
    iff the parsed timestamp had to be pinned to a boundary, useful so the
    caller can audit-tag the resulting alert.
    """
    return coerce_with_bounds(event, now=now)


def _as_dict(value: object) -> dict:
    """``value`` if it is an object, else an empty one: ``events: list[dict]`` only checks the top level, so a nested ``actor`` / ``client`` can be a string or a number."""
    return value if isinstance(value, dict) else {}


def _synthesise_alert_from_events(
    *,
    tenant_id: uuid.UUID,
    events: list[dict],
    connector_type: str | None,
    override_title: str | None,
    override_description: str | None,
    override_severity: str | None,
    override_tags: list[str] | None,
    idempotency_key: str | None = None,
) -> Alert:
    """Build a single ``Alert`` row that represents the submitted event batch.

    The shape of incoming events is intentionally loose — they may be raw
    OCSF, Okta system-log entries, or any dict with the usual suspects
    (``displayMessage``, ``severity``, ``actor``, ``client``, ``published``).
    The function extracts what it can and falls back to safe defaults.

    Callers should hand us **already sanitised** events
    (:func:`app.services.event_sanitiser.sanitise_event_batch`) so that
    bearer tokens / API keys / passwords embedded in connector payloads
    never reach ``alerts.raw_event``. We do **not** redact in here because
    we still want to surface the raw shape for diagnostics — sanitisation
    is the endpoint's responsibility, this function trusts its input.

    ``idempotency_key`` is plumbed through to the resulting ORM instance
    so the caller can persist it atomically with the row. The synthesise
    function itself does no lookup — that's the endpoint's job.
    """
    first = events[0] if events else {}

    # Title
    title = override_title or first.get("displayMessage") or first.get("eventType") or first.get("name") or "A.C.O.R.N submitted alert"

    # Severity: pick the highest in the batch unless overridden
    severities = [_normalize_severity(e.get("severity")) for e in events]
    severity = _normalize_severity(override_severity) if override_severity else (_max_severity(severities) if severities else "medium")
    priority = _SEVERITY_PRIORITY[severity]

    # Description: count + first event hint
    description = override_description or (f"Submitted via aisoc submit / API. {len(events)} event(s) in batch. First event: {title}.")

    # Affected entities
    affected_ips: list[str] = []
    affected_hosts: list[str] = []
    affected_users: list[str] = []
    earliest: datetime | None = None
    latest: datetime | None = None
    # We need a single ``now`` reference so every timestamp in the batch
    # is clamped against the same window — otherwise a batch that takes
    # 50ms to process could clamp the first event's "max future" to one
    # value and the last event's to another, which would be confusing
    # to debug and arguably wrong.
    now = now_utc()
    any_clamped = False

    for event in events:
        actor = _as_dict(event.get("actor"))
        client = _as_dict(event.get("client"))

        # User: collect candidate identifiers in priority order; skip the
        # actor entirely if *any* of them already appears in
        # ``affected_users`` (i.e. we've already recorded this person under
        # a different identifier in an earlier event).
        actor_identifiers = [
            actor[key] for key in ("alternateId", "displayName", "email", "name", "id") if isinstance(actor.get(key), str) and actor[key]
        ]
        if actor_identifiers and not any(ident in affected_users for ident in actor_identifiers):
            affected_users.append(actor_identifiers[0])

        # IP from client
        ip = client.get("ipAddress") or client.get("ip")
        if isinstance(ip, str) and ip and ip not in affected_ips:
            affected_ips.append(ip)

        # Host from client geographicalContext or client.id
        geo = _as_dict(client.get("geographicalContext"))
        host_hint = client.get("device") or client.get("id") or geo.get("city")
        if isinstance(host_hint, str) and host_hint and host_hint not in affected_hosts:
            affected_hosts.append(host_hint)

        # Timestamps — bounded against MIN_AGE / MAX_FUTURE so a broken
        # connector emitting 1970-01-01 or 2099-12-31 doesn't poison the
        # SLA timers or push the alert outside the retention window.
        ts, clamped = _coerce_published(event, now=now)
        if clamped:
            any_clamped = True
        if ts is not None:
            if earliest is None or ts < earliest:
                earliest = ts
            if latest is None or ts > latest:
                latest = ts

    event_time = latest or earliest or now
    first_seen = earliest or now
    last_seen = latest or now

    # Tags: combine override + a marker so demo alerts are recognisable.
    # When *any* event in the batch had its timestamp clamped, drop an
    # ``ts-clamped`` tag so analysts (and the audit log) can spot a
    # source-side timestamp problem without re-running the math.
    tags = list(override_tags or [])
    if "submitted" not in tags:
        tags.append("submitted")
    if connector_type and connector_type not in tags:
        tags.append(connector_type)
    if any_clamped and "ts-clamped" not in tags:
        tags.append("ts-clamped")

    return Alert(
        tenant_id=tenant_id,
        title=title,
        description=description,
        severity=severity,
        status="new",
        priority=priority,
        category="identity" if "okta" in (connector_type or "").lower() else None,
        connector_type=connector_type,
        # JSONB list columns: populate explicitly so the response model
        # validation never trips on ``None`` for fresh inserts (the
        # ``default=list`` column default only fires after a real flush
        # against Postgres, not in unit tests with a mocked session).
        mitre_tactics=[],
        mitre_techniques=[],
        ai_recommendations=[],
        affected_ips=affected_ips,
        affected_hosts=affected_hosts,
        affected_users=affected_users,
        tags=tags,
        raw_event={
            "events": events,
            "connector_type": connector_type,
            "source": "aisoc-submit-api",
            "timestamps_clamped": any_clamped,
        },
        event_time=event_time,
        first_seen=first_seen,
        last_seen=last_seen,
        created_at=now,
        updated_at=now,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/submit",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_alert(
    payload: AlertSubmitRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: TenantDBSession,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Optional opaque client-supplied key (8–128 chars, "
                "[A-Za-z0-9._:-]). When supplied, a retry of the same key "
                "for the same tenant returns the existing alert with HTTP "
                "200 instead of creating a duplicate."
            ),
        ),
    ] = None,
) -> AlertResponse:
    """Submit one alert directly from an OCSF event batch.

    This is the destination for `aisoc submit <file>` and the local-dev fast
    path documented in the quickstart. We deliberately bypass the Kafka
    detect/correlate/fuse pipeline (which fresh clones don't run by default)
    so that a hand-crafted fixture lands in the database — and therefore in
    ``GET /api/v1/alerts`` and the web console — within the same second.

    **Hardening (Batch 8 / H-5)**:

    * **Payload caps** — events are first run through
      :func:`app.services.event_sanitiser.sanitise_event_batch`, which
      enforces ``AISOC_SUBMIT_MAX_EVENTS`` (default 200), per-event size
      ``AISOC_SUBMIT_MAX_EVENT_BYTES`` (default 64 KiB), and total batch
      size ``AISOC_SUBMIT_MAX_TOTAL_BYTES`` (default 1 MiB). Violations
      return ``413 Payload Too Large`` rather than the 200 OK + truncated
      alert we used to silently emit.
    * **Secret redaction** — the sanitiser also redacts keys matching
      common secret patterns (``password``, ``token``, ``api_key``, …)
      *before* the payload is persisted to ``alerts.raw_event``, so a
      leaky connector cannot smuggle bearer tokens into the alert table
      where they would be visible to every analyst with ``alerts:read``.
    * **Idempotency** — when the client supplies an ``Idempotency-Key``
      header, the resulting alert is keyed ``(tenant_id, idempotency_key)``
      via a partial unique index (migration ``044``). A retry of the
      same key resolves to the existing row and returns HTTP ``200``
      instead of creating a duplicate, so at-least-once connectors and
      the ``aisoc submit`` CLI can retry safely on network blips.
    * **Timestamp bounds** — event timestamps outside the configured
      retention window are clamped (see
      :mod:`app.services.timestamp_bounds`); the resulting alert is
      tagged ``ts-clamped`` so analysts can see the connector misbehaved.

    Authorisation: requires ``alerts:write``. In development mode the
    auth bypass in :mod:`app.api.v1.deps` resolves to the deterministic
    demo tenant, so the documented ``aisoc submit`` CLI works against a
    fresh clone with no token plumbing.
    """
    if not payload.events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="events must be a non-empty list",
        )

    # Validate Idempotency-Key shape early so a bad header fails fast
    # and never costs us a DB round-trip. We only enforce the regex when
    # the client *supplied* a key — the column itself remains nullable.
    #
    # We also strip CR/LF immediately after the regex passes. The regex
    # already forbids those characters (the charset is [A-Za-z0-9._:-]),
    # so this is a no-op for any well-formed key, but it makes the
    # sanitisation explicit at the source. CodeQL's ``py/log-injection``
    # taint analysis does not understand regex-based validation, so
    # without this explicit ``.replace`` it keeps flagging every
    # downstream ``logger.*(extra={"idempotency_key": idempotency_key})``
    # call as a log-injection sink.
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip().replace("\r", "").replace("\n", " ")
        if not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Idempotency-Key must be 8–128 ASCII chars matching [A-Za-z0-9._:-]"),
            )

        # Cheap check first — if a row with this (tenant, key) already
        # exists, return it without doing any sanitisation/synthesis
        # work. This is the hot path for connector retries.
        existing = await db.execute(
            select(Alert).where(
                and_(
                    Alert.tenant_id == current_user.tenant_id,
                    Alert.idempotency_key == idempotency_key,
                )
            )
        )
        cached = existing.scalar_one_or_none()
        if cached is not None:
            logger.info(
                "alert.submitted.idempotent_hit",
                extra={
                    "alert_id": str(cached.id),
                    "tenant_id": str(cached.tenant_id),
                    "idempotency_key": _log_safe(idempotency_key),
                },
            )
            return AlertResponse.model_validate(cached)

    # Sanitise the batch: redact secrets and enforce size caps. Only the
    # *batch-length* cap raises ``SubmitPayloadTooLarge`` (translated to
    # HTTP 413) — per-event and total-bytes overruns are handled inline
    # by the sanitiser by replacing oversized payloads with a small
    # truncation marker, so one rogue event doesn't drop the rest of the
    # batch. The ``stats`` dict gives us a one-line audit summary of what
    # was redacted/truncated.
    try:
        sanitised_events, sanitise_stats = sanitise_event_batch(payload.events)
    except SubmitPayloadTooLarge as exc:
        logger.warning(
            "alert.submit.payload_too_large",
            extra={
                "tenant_id": str(current_user.tenant_id),
                "reason": str(exc),
                "raw_event_count": len(payload.events),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc

    alert = _synthesise_alert_from_events(
        tenant_id=current_user.tenant_id,
        events=sanitised_events,
        connector_type=payload.connector_type,
        override_title=payload.title,
        override_description=payload.description,
        override_severity=payload.severity,
        override_tags=payload.tags,
        idempotency_key=idempotency_key,
    )

    db.add(alert)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Race condition: another concurrent request landed the same
        # (tenant_id, idempotency_key) between our SELECT above and our
        # INSERT. The partial unique index from migration 044 catches
        # this — rather than 500ing, roll back and return whichever row
        # actually won the race, preserving the idempotency contract.
        await db.rollback()
        if idempotency_key is None:
            # Not an idempotency race — re-raise as a generic 500 so
            # the operator sees the real issue (e.g. NOT NULL violation
            # on a column we forgot to populate).
            logger.exception("alert.submit.integrity_error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to persist alert",
            ) from exc

        existing = await db.execute(
            select(Alert).where(
                and_(
                    Alert.tenant_id == current_user.tenant_id,
                    Alert.idempotency_key == idempotency_key,
                )
            )
        )
        cached = existing.scalar_one_or_none()
        if cached is None:
            # The unique index complained but no row is visible — this
            # really is a 500. Don't pretend it succeeded.
            logger.exception(
                "alert.submit.idempotency_race_no_row",
                extra={
                    "tenant_id": str(current_user.tenant_id),
                    "idempotency_key": _log_safe(idempotency_key),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to persist alert",
            ) from exc

        logger.info(
            "alert.submitted.idempotent_race_resolved",
            extra={
                "alert_id": str(cached.id),
                "tenant_id": str(cached.tenant_id),
                "idempotency_key": _log_safe(idempotency_key),
            },
        )
        return AlertResponse.model_validate(cached)

    await db.refresh(alert)

    logger.info(
        "alert.submitted",
        extra={
            "alert_id": str(alert.id),
            "tenant_id": str(alert.tenant_id),
            "severity": alert.severity,
            "events": len(sanitised_events),
            "connector_type": _log_safe(payload.connector_type),
            "idempotency_key": _log_safe(idempotency_key),
            "timestamps_clamped": "ts-clamped" in (alert.tags or []),
            "redacted_keys": sanitise_stats.get("redacted", 0),
            "truncated_events": sanitise_stats.get("truncated", 0),
        },
    )

    return AlertResponse.model_validate(alert)


def _aware(moment: datetime) -> datetime:
    return as_utc(moment)


def _repeat_key() -> tuple:
    """What makes two alerts repeats of each other: the same rule (or title) about the same machines and the same users."""
    # The client is part of the key: two clients can each have a machine called PC-01, and their alerts are never repeats of each other (this lets several clients be read in one query).
    return (
        Alert.tenant_id,
        func.lower(func.coalesce(Alert.rule_name, Alert.title)),
        cast(Alert.affected_hosts, Text),
        cast(Alert.affected_users, Text),
    )


async def _newest_of_each_repeat(db: Any, flt: Any, limit: int, offset: int) -> tuple[int, list[tuple[Alert, int]]]:
    """The newest alert of each group of repeats among those matching ``flt``: how many groups there are, and one page of them (newest first) with each group's size."""
    key = _repeat_key()
    ranked = (
        select(
            Alert.id.label("id"),
            func.row_number().over(partition_by=key, order_by=(Alert.created_at.desc(), Alert.id)).label("rn"),
            func.count().over(partition_by=key).label("n"),
        )
        .where(flt)
        .subquery()
    )
    total = (await db.execute(select(func.count()).select_from(ranked).where(ranked.c.rn == 1))).scalar_one()
    found = (
        await db.execute(
            select(Alert, ranked.c.n)
            .join(ranked, ranked.c.id == Alert.id)
            .where(ranked.c.rn == 1)
            .order_by(Alert.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return total, [(alert, int(n)) for alert, n in found]


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: TenantDBSession,
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=25, ge=1, le=200),
    severity: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=64),
    category: str | None = Query(default=None, max_length=128),
    assigned_to_me: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    min_confidence: int | None = Query(default=None, ge=0, le=100),
    confidence_label: str | None = Query(default=None, max_length=64),
    source: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$"),
    client_id: uuid.UUID | None = Query(default=None),
    device: str | None = Query(default=None, max_length=255),
    since: Annotated[
        datetime | None,
        Query(description="Only alerts received at or after this time (ISO 8601; a time with no zone counts as UTC)."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="Only alerts received before this time (ISO 8601; a time with no zone counts as UTC)."),
    ] = None,
    # Named ``person`` (not ``user``): a query parameter called ``user`` reads like the signed-in user object, and a guard test refuses that name.
    person: Annotated[
        str | None,
        Query(max_length=320, description="Only alerts that name this person (an affected user, matched exactly, ignoring case)."),
    ] = None,
    ticket: str | None = Query(
        default=None, pattern="^(linked|none)$", description="linked: only alerts with a HaloPSA ticket; none: only alerts without one."
    ),
    collapse: bool = Query(
        default=False,
        description="Show one row for each group of repeats (same rule, machines and users): the newest, with ``repeat_count`` saying how many there are.",
    ),
) -> AlertListResponse:
    """List alerts for the current tenant and its client tenants, with filtering and pagination.

    An MSSP parent sees its own alerts plus those of its client tenants (each row carries ``client_name``); ``client_id`` narrows the list to
    one tenant (the caller's own or one of its clients). A tenant with no clients sees only its own alerts, as before.

    `source` is the tool an alert came from as CORE names it (``huntress``, ``petra``, ``blumira``). Alerts forwarded by CORE arrive through the generic JSON inbox, so their
    product is all "Generic JSON"; the tool is the sender's own ``source`` field, which the inbox template keeps at ``raw_event.source``.

    `device` narrows the list to alerts about one machine, by the host name the alert carries (compared without regard to case).

    `min_confidence` / `confidence_label` let the queue workbench (PR-5) and
    /alerts page filter on the fusion-emitted confidence signal (W3). Alerts
    that pre-date the confidence column will have NULL and therefore won't
    match either filter — that's intentional; analysts who care about
    confidence should only see alerts that actually carry the signal.
    """
    # A date range on when the alert was received. The page works out "today", "yesterday" and the like in the person's own time zone and sends the two instants.
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if since is not None and until is not None and until <= since:
        raise HTTPException(status_code=422, detail="until must be after since")
    date_filters: list = []
    if since is not None:
        date_filters.append(Alert.created_at >= since)
    if until is not None:
        date_filters.append(Alert.created_at < until)

    collapse = (
        collapse is True
    )  # called directly (without FastAPI), an omitted parameter is its Query() default, which must not read as "on"
    if confidence_label is not None and confidence_label not in {"high", "medium", "low"}:
        # NOTE: the local `status` query parameter shadows the `fastapi.status` module here, so use the literal 400.
        raise HTTPException(status_code=400, detail="confidence_label must be one of: high, medium, low")

    # `search` is plain text: % and _ are matched literally, and a blank search is no search.
    term = (search or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    client_hits: set[uuid.UUID] = set()
    device_name = (device or "").strip()
    # The list is stored as JSON text like ["HCC-FS01", "other"]: look for the quoted name so "FS01" does not match "HCC-FS01", and take % and _ literally.
    device_like = (
        "%" + json.dumps(device_name.lower(), ensure_ascii=False).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if device_name
        else ""
    )

    # The same for a person: affected_users is stored as JSON text like ["amy@acme.com"], so the quoted name is looked for (a part of an address does not match).
    user_name = (person or "").strip()
    user_like = (
        "%" + json.dumps(user_name.lower(), ensure_ascii=False).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if user_name
        else ""
    )

    def filters_for(tenant_id: uuid.UUID, tenant_predicate: Any = None) -> list:
        filters = [tenant_predicate if tenant_predicate is not None else Alert.tenant_id == tenant_id, *date_filters]
        if severity:
            filters.append(Alert.severity == severity)
        if status == OPEN_STATUS:
            filters.append(Alert.status.notin_(FINISHED_STATUSES))
        elif status:
            filters.append(Alert.status == status)
        else:
            # Alerts hidden by a "hide this alert type" rule stay out of the list unless they are asked for (status=suppressed).
            filters.append(Alert.status.notin_(("suppressed", "stale")))
        if category:
            filters.append(Alert.category == category)
        if ticket == "linked":
            filters.append(has_ticket_expr())
        elif ticket == "none":
            filters.append(not_(has_ticket_expr()))
        if assigned_to_me:
            filters.append(Alert.assigned_to_id == current_user.user_id)
        if source:
            filters.append(Alert.raw_event["source"].astext == source)
        if device_name:
            # affected_hosts is a JSON list of names; match one element exactly, ignoring case.
            filters.append(func.lower(cast(Alert.affected_hosts, Text)).like(device_like, escape="\\"))
        if user_name:
            filters.append(func.lower(cast(Alert.affected_users, Text)).like(user_like, escape="\\"))
        if min_confidence is not None:
            filters.append(Alert.confidence >= min_confidence)
        if confidence_label is not None:
            filters.append(Alert.confidence_label == confidence_label)
        if term and tenant_id not in client_hits:
            # The text is in the title, the description (CORE puts the device and client there) or the rule name; a client's name matches all of that client's alerts.
            like = f"%{term}%"
            text_match = or_(
                Alert.title.ilike(like, escape="\\"), Alert.description.ilike(like, escape="\\"), Alert.rule_name.ilike(like, escape="\\")
            )
            filters.append(text_match)
        return filters

    # The caller's client tenants (empty for an ordinary tenant).
    clients = {
        row.id: row.name
        for row in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == current_user.tenant_id))).all()
    }
    if client_id is not None and client_id != current_user.tenant_id and client_id not in clients:
        raise HTTPException(status_code=404, detail="Client not found")
    scope = [client_id] if client_id is not None else [current_user.tenant_id, *clients]
    if term:
        plain = (search or "").strip().lower()
        client_hits.update(tid for tid, name in clients.items() if plain in name.lower())

    tally = {"total": 0, "critical": 0, "high": 0, "unresolved": 0, "no_ticket": 0}
    holding: set[uuid.UUID] | None = None

    async def add_tally(tid: uuid.UUID) -> int:
        """Add one tenant's counts to the tally and return how many alerts it has (under the ``source`` filter). The caller has the session scoped to that tenant."""
        base = (
            and_(Alert.tenant_id == tid, *date_filters, Alert.raw_event["source"].astext == source)
            if source
            else and_(Alert.tenant_id == tid, *date_filters)
        )
        grouped = (
            await db.execute(select(Alert.severity, Alert.status, func.count()).where(base).group_by(Alert.severity, Alert.status))
        ).all()
        if not grouped:
            return 0  # nothing here, so nothing without a ticket either: one query instead of two
        tally["no_ticket"] += (
            await db.execute(
                select(func.count()).select_from(Alert).where(and_(base, Alert.status.notin_(FINISHED_STATUSES), not_(has_ticket_expr())))
            )
        ).scalar_one() or 0
        for sev, st, n in grouped:
            tally["total"] += n
            tally["critical"] += n if sev == "critical" else 0
            tally["high"] += n if sev == "high" else 0
            tally["unresolved"] += n if st in _UNRESOLVED else 0
        return sum(n for _sev, _st, n in grouped)

    offset = (page - 1) * page_size
    repeats: dict[uuid.UUID, int] = {}
    tallied: set[uuid.UUID] = set()
    if len(scope) == 1 and scope[0] == current_user.tenant_id and collapse:
        flt = and_(*filters_for(scope[0]))
        total, found = await _newest_of_each_repeat(db, flt, page_size, offset)
        rows = [alert for alert, _n in found]
        repeats = {alert.id: n for alert, n in found}
    elif len(scope) == 1 and scope[0] == current_user.tenant_id:
        # The common case: one tenant, one paginated query.
        flt = and_(*filters_for(scope[0]))
        total = (await db.execute(select(func.count()).select_from(Alert).where(flt))).scalar_one()
        rows = (
            (await db.execute(select(Alert).where(flt).order_by(Alert.created_at.desc()).offset(offset).limit(page_size))).scalars().all()
        )
    else:
        # Several tenants: ONE read across all of them. Entering each client in turn (four or more statements apiece before the query itself) took two to eight seconds for an organization with a hundred
        # clients holding alerts, and the database itself answers in well under a second. Every query still names exactly the clients it reads (``tenant_id IN`` the caller's scope), inside the
        # sanctioned cross-tenant read block, and clients that hold no alerts are left out as before.
        holding = await tenants_holding_alerts(db, scope)
        reading = [t for t in scope if holding is None or t in holding]
        hit = [t for t in reading if t in client_hits]
        rest = [t for t in reading if t not in client_hits]
        parts = []
        if hit:  # a client whose name matched the search: all its alerts, the text is not asked of them
            parts.append(and_(*filters_for(hit[0], Alert.tenant_id.in_(hit))))
        if rest:
            parts.append(and_(*filters_for(rest[0], Alert.tenant_id.in_(rest))))
        flt = or_(*parts) if parts else false()
        async with cross_tenant_reads(db):
            if reading:
                scoped_base = (
                    and_(Alert.tenant_id.in_(reading), *date_filters, Alert.raw_event["source"].astext == source)
                    if source
                    else and_(Alert.tenant_id.in_(reading), *date_filters)
                )
                for sev, st, n in (
                    await db.execute(
                        select(Alert.severity, Alert.status, func.count()).where(scoped_base).group_by(Alert.severity, Alert.status)
                    )
                ).all():
                    tally["total"] += n
                    tally["critical"] += n if sev == "critical" else 0
                    tally["high"] += n if sev == "high" else 0
                    tally["unresolved"] += n if st in _UNRESOLVED else 0
                if tally["total"]:
                    tally["no_ticket"] += (
                        await db.execute(
                            select(func.count())
                            .select_from(Alert)
                            .where(and_(scoped_base, Alert.status.notin_(FINISHED_STATUSES), not_(has_ticket_expr())))
                        )
                    ).scalar_one() or 0
            tallied.update(scope)
            if collapse:
                total, found = await _newest_of_each_repeat(db, flt, page_size, offset)
                rows = [alert for alert, _n in found]
                repeats = {alert.id: n for alert, n in found}
            else:
                total = (await db.execute(select(func.count()).select_from(Alert).where(flt))).scalar_one()
                rows = (
                    (await db.execute(select(Alert).where(flt).order_by(Alert.created_at.desc(), Alert.id).offset(offset).limit(page_size)))
                    .scalars()
                    .all()
                )

    # The tally covers the whole scope (within the chosen dates), so it doesn't change as the severity / status buttons are used.
    for tid in scope:
        if tid in tallied:
            continue
        if len(scope) > 1 and holding is not None and tid not in holding:
            continue
        if len(scope) == 1 and scope[0] == current_user.tenant_id:
            await add_tally(tid)
        else:
            async with acting_as_tenant(db, tid):
                await add_tally(tid)

    items = []
    for a in rows:
        item = AlertResponse.model_validate(a)
        item.client_name = clients.get(a.tenant_id)
        item.source = _tool_of(a)
        if collapse:
            item.repeat_count = repeats.get(a.id, 1)
        items.append(item)
    return AlertListResponse(
        summary=AlertSummary(**tally), items=items, total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size
    )


@router.get("/stats", response_model=AlertStatsResponse)
async def get_alert_stats(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
) -> AlertStatsResponse:
    """Get alert statistics for the dashboard."""
    from datetime import timedelta

    # Alerts hidden by a "hide this alert type" rule are not counted anywhere.
    tenant_filter = and_(Alert.tenant_id == current_user.tenant_id, Alert.status != "suppressed")

    # Total count
    total_result = await db.execute(select(func.count()).select_from(Alert).where(tenant_filter))
    total = total_result.scalar_one()

    # By severity
    sev_result = await db.execute(select(Alert.severity, func.count()).where(tenant_filter).group_by(Alert.severity))
    by_severity = {row[0]: row[1] for row in sev_result.all()}

    # By status
    status_result = await db.execute(select(Alert.status, func.count()).where(tenant_filter).group_by(Alert.status))
    by_status = {row[0]: row[1] for row in status_result.all()}

    # New last 24h
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    new_24h_result = await db.execute(select(func.count()).select_from(Alert).where(and_(tenant_filter, Alert.created_at >= cutoff)))
    new_last_24h = new_24h_result.scalar_one()

    # Critical open
    crit_result = await db.execute(
        select(func.count())
        .select_from(Alert)
        .where(and_(tenant_filter, Alert.severity == "critical", Alert.status.in_(["new", "triaging", "in_progress"])))
    )
    critical_open = crit_result.scalar_one()

    return AlertStatsResponse(
        total=total,
        by_severity=by_severity,
        by_status=by_status,
        new_last_24h=new_last_24h,
        critical_open=critical_open,
    )


# NOTE: `/queue` is defined here — *before* `/{alert_id}` — on purpose.
# FastAPI matches routes top-down, so a static path must precede the
# parametric path of the same depth or the framework will route
# `GET /alerts/queue` into `get_alert(alert_id="queue")` and 422.
@router.get("/queue", response_model=QueueResponse)
async def get_alert_queue(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: TenantDBSession,
    owner: Literal["me", "unassigned", "all"] = Query(default="all"),
    period: Literal["24h", "7d", "30d", "all"] = Query(default="all"),
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=50, ge=1, le=200),
) -> QueueResponse:
    """Investigation Queue workbench feed.

    Returns the prioritised list of alerts the analyst should work on
    next: alerts assigned to them, followed by unassigned
    critical/high alerts, ordered by SLA due time.

    The endpoint also returns ``counts`` for both buckets unconditionally
    so the topbar badge and the workbench tabs can render without an
    extra round-trip.
    """
    return await build_queue(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        owner=owner,
        period=period,
        page=page,
        page_size=page_size,
    )


@router.get("/{alert_id}/earlier-outcomes")
async def earlier_outcomes(
    alert_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> dict[str, Any]:
    """What usually happened to earlier alerts of the same kind (same client, same exact title, last 180 days): how they ended, how often a ticket was made, the median time. Counts only, and "too few" under three."""
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        this = (await db.execute(select(Alert.title).where(Alert.id == alert_id, Alert.tenant_id == tid))).first()
        if this is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        since = datetime.now(UTC) - timedelta(days=alert_outcomes.WINDOW_DAYS)
        found = (
            await db.execute(
                select(
                    Alert.status,
                    Alert.disposition,
                    has_ticket_expr().label("has_ticket"),
                    Alert.created_at,
                    Alert.resolved_at,
                    Alert.stale_at,
                )
                .where(Alert.tenant_id == tid, Alert.title == this[0], Alert.id != alert_id, Alert.created_at >= since)
                .limit(2000)
            )
        ).all()
    return alert_outcomes.summarize(
        [
            {"status": r[0], "disposition": r[1], "has_ticket": bool(r[2]), "created_at": r[3], "resolved_at": r[4], "stale_at": r[5]}
            for r in found
        ]
    )


@router.get("/{alert_id}/other-clients")
async def same_alert_at_other_clients(
    alert_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> dict[str, Any]:
    """The same alert (same exact title) raised in the last 24 hours at the caller's other tenants: per client, how many and the newest one. Empty for an organization with no clients."""
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        this = (await db.execute(select(Alert.title, Alert.raw_event).where(Alert.id == alert_id, Alert.tenant_id == tid))).first()
        if this is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    # A posture check fails at many clients for ordinary reasons: the same title elsewhere is not a campaign, so nothing is said.
    if alert_other_clients.is_posture_check(this[1]):
        return alert_other_clients.nothing()
    # Only the caller's own organization and the clients it owns, never anything else; the tenant holding this alert is left out.
    names = {
        row.id: row.name
        for row in (
            await db.execute(
                select(Tenant.id, Tenant.name).where(
                    or_(Tenant.parent_tenant_id == current_user.tenant_id, Tenant.id == current_user.tenant_id)
                )
            )
        ).all()
    }
    others = [t for t in names if t != tid]
    if not others or not this[0]:
        return alert_other_clients.nothing()
    since = datetime.now(UTC) - timedelta(hours=alert_other_clients.WINDOW_HOURS)
    async with cross_tenant_reads(db):
        found = (
            await db.execute(
                select(Alert.tenant_id, Alert.id, Alert.created_at)
                .where(
                    Alert.tenant_id.in_(others),
                    Alert.title == this[0],
                    Alert.created_at >= since,
                    Alert.status.notin_(("suppressed", "stale")),
                )
                .order_by(Alert.created_at.desc())
                .limit(alert_other_clients.ROW_CAP)
            )
        ).all()
    return alert_other_clients.summarize([{"tenant_id": r[0], "id": r[1], "created_at": r[2]} for r in found], names)


@router.get("/{alert_id}", response_model=AlertDetailResponse)
async def get_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
) -> AlertDetailResponse:
    """Get a single alert by ID, enriched with Investigation Rail data.

    The endpoint returns the standard alert fields plus everything the
    rail needs to render in one shot:

    * a deterministic ``narrative`` (lazily filled and persisted if the
      row was created before fusion started emitting it),
    * ``related_entities`` grouped for pivot,
    * a compact ``mini_timeline``,
    * normalised ``recommended_actions``.

    The lazy-fill is best-effort: if the narrative builder ever raises
    we log and return the alert with ``narrative=None`` so the page
    keeps rendering. The frontend already handles the null case.
    """
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))
        alert = result.scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        # ── Lazy-fill narrative for legacy rows ─────────────────────────────
        # New alerts get a narrative at fusion time. Older rows predate that
        # column being populated; the first detail-view read materialises
        # and persists one so we only pay the cost once per row.
        # A narrative stored with the inbox's name where the tool's belongs ("from `Generic Generic JSON`") is written again the same way, once.
        if not alert.narrative or narrative_names_the_inbox(alert.narrative):
            try:
                inputs = project_alert_to_narrative_inputs(alert)
                narrative_text = build_narrative(inputs)
                if narrative_text:
                    alert.narrative = narrative_text
                    await db.execute(
                        update(Alert).where(Alert.id == alert.id).values(narrative=narrative_text, updated_at=datetime.now(UTC))
                    )
                    await db.commit()
            except Exception:  # noqa: BLE001 — never let narrative kill a detail view
                logger.warning(
                    "narrative lazy-fill failed for alert %s; serving without narrative",
                    alert.id,
                    exc_info=True,
                )

        envelope = await build_rail_envelope(db, alert)

        # ``model_validate`` against the parent class to inherit field
        # coercion, then merge the rail fields. We don't add the rail data
        # to the ORM model — keeping the envelope construction in the view
        # layer means the rail can evolve without migrations.
        payload = AlertDetailResponse.model_validate(alert)
        client_name = None
        if tid != current_user.tenant_id:
            client_name = (await db.execute(select(Tenant.name).where(Tenant.id == tid))).scalar_one_or_none()
        return payload.model_copy(
            update={
                "source": _tool_of(alert),
                "source_url": _source_url_of(alert, await _huntress_base_if_needed(db, alert, {tid, current_user.tenant_id})),
                "links": _links_of(alert),
                "client_name": client_name,
                "narrative": alert.narrative,
                "related_entities": envelope.related_entities,
                "mini_timeline": envelope.mini_timeline,
                "recommended_actions": envelope.recommended_actions,
            }
        )


def _links_of(alert: Any) -> dict[str, str]:
    """The device and user links the tool's data gave (``raw_event.links``), kept only for the known keys and only as plain https addresses."""
    raw = alert.raw_event if isinstance(getattr(alert, "raw_event", None), dict) else {}
    found = raw.get("links")
    if not isinstance(found, dict):
        return {}
    return {
        k: v
        for k in ("device_url", "user_url")
        if isinstance(v := found.get(k), str) and len(v) <= 1000 and re.fullmatch(r"https://\S+", v, re.IGNORECASE)
    }


# A full match, not ``$``: ``$`` also matches before a trailing newline, so "https://x" + newline passed.
_HTTPS = re.compile(r"https://\S+", re.IGNORECASE)
_THREATMATE_ALERTS = "https://app.threatmate.com/alerts"


def _source_url_of(alert: Any, huntress_base: str | None = None) -> str | None:
    """The tool's own link to this alert: the one it sent (``raw_event.url``), kept only when it is a plain https address; else one built from the ids the alert carries.

    Alerts stored before the forwarder sent a link have none, so ThreatMate's is built from its client and finding ids, and a Huntress escalation's from its id and the account address
    ``huntress_base`` that the tool's other escalations show (see ``_huntress_base``).
    """
    raw = alert.raw_event if isinstance(getattr(alert, "raw_event", None), dict) else {}
    url = raw.get("url")
    if isinstance(url, str) and len(url) <= 1000 and _HTTPS.fullmatch(url):
        return url
    unmapped = raw.get("unmapped")
    context = unmapped.get("context") if isinstance(unmapped, dict) else None
    context = context if isinstance(context, dict) else {}
    source = raw.get("source")
    if source == "threatmate":
        client, finding = str(context.get("threatmate_client_id") or ""), str(context.get("threatmate_alert_id") or "")
        if client.isdigit() and finding.isdigit():
            return f"{_THREATMATE_ALERTS}?tenantId={client}&finding={finding}"
    if source == "huntress" and huntress_base:
        escalation = str(context.get("huntress_escalation_id") or "")
        if escalation.isdigit():
            return f"{huntress_base}/{escalation}"
    return None


async def _huntress_base_if_needed(db: Any, alert: Any, tenant_ids: set) -> str | None:
    """The account address only for a Huntress alert that carries no link of its own: any other alert costs no extra query."""
    raw = alert.raw_event if isinstance(getattr(alert, "raw_event", None), dict) else {}
    if raw.get("source") != "huntress" or isinstance(raw.get("url"), str):
        return None
    return await _huntress_base(db, tenant_ids)


async def _huntress_base(db: Any, tenant_ids: set) -> str | None:
    """``https://<account>.huntress.io/account/escalations`` as the tenant's other Huntress alerts spell it, or None when none has a link."""
    try:
        found = (
            await db.execute(
                select(Alert.raw_event["url"].astext)
                .where(
                    Alert.tenant_id.in_(tenant_ids),
                    Alert.raw_event["source"].astext == "huntress",
                    Alert.raw_event["url"].astext.like("https://%/account/escalations/%"),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - a missing convenience link must never fail the alert
        return None
    if not isinstance(found, str) or not _HTTPS.fullmatch(found):
        return None
    return found.rsplit("/", 1)[0]


class BulkCloseRequest(BaseModel):
    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: Literal["resolved", "false_positive", "closed"] = "resolved"
    reason: str = Field(
        min_length=3, max_length=500, description="Why these alerts are being closed. Kept in the audit log against each alert."
    )


class ClosedItem(BaseModel):
    id: uuid.UUID
    status_from: str


class BulkCloseResponse(BaseModel):
    closed: int
    already_finished: int
    not_found: int
    status: str
    reason: str
    # What was closed and the status each had before, so the close can be undone for a few minutes (POST /alerts/bulk-close/undo).
    closed_items: list[ClosedItem] = []


@router.post("/bulk-close", response_model=BulkCloseResponse)
async def bulk_close_alerts(
    body: BulkCloseRequest,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: DBSession,
) -> BulkCloseResponse:
    """Close up to 200 alerts at once, with one reason. An alert that is already finished is left as it is (and counted); one the caller cannot see is counted as not found.

    The reason and the status before and after are written to the audit log for each alert closed. A false-positive close also sets the alert's verdict, so the false-positive rate counts it. This changes
    nothing the AI learns from (no override is recorded): a bulk close is housekeeping, not a correction of a verdict.
    """
    reason = " ".join(body.reason.split())
    if len(reason) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give a reason of at least three characters.")
    closed = already = missing = 0
    batch = uuid.uuid4().hex[:12]  # one id on every audit entry of this call, so one close of 180 alerts can be found as one thing
    closed_items: list[ClosedItem] = []
    for alert_id in dict.fromkeys(body.alert_ids):
        try:
            async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
                alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
                if alert is None:
                    missing += 1
                    continue
                if alert.status in FINISHED_STATUSES:
                    already += 1
                    continue
                before = alert.status
                now = datetime.now(UTC)
                values: dict = {"status": body.status, "resolved_at": now, "updated_at": now}
                if alert.first_seen_at is None:
                    values["first_seen_at"] = now  # the first time a person acted on it: what MTTA is measured to
                if body.status == "false_positive":
                    values["disposition"] = "false_positive"
                await db.execute(update(Alert).where(Alert.id == alert_id).values(**values))
                await emit_audit(
                    db=db,
                    tenant_id=tid,
                    actor_id=current_user.user_id,
                    action="alerts:bulk_close",
                    resource="alert",
                    resource_id=str(alert_id),
                    changes={"status_from": before, "status_to": body.status, "reason": reason, "batch": batch},
                    request=request,
                )
                closed += 1
                closed_items.append(ClosedItem(id=alert_id, status_from=before))
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            missing += 1
    await db.commit()
    return BulkCloseResponse(
        closed=closed, already_finished=already, not_found=missing, status=body.status, reason=reason, closed_items=closed_items
    )


BULK_CLOSE_UNDO_MINUTES = 10


class UndoItem(BaseModel):
    id: uuid.UUID
    status_from: str = Field(
        pattern=r"^[a-z_]{1,32}$", description="The status the alert had before the bulk close, as the close answered it."
    )


class BulkCloseUndoRequest(BaseModel):
    items: list[UndoItem] = Field(min_length=1, max_length=200)
    status: Literal["resolved", "false_positive", "closed"] = Field(description="The status the bulk close gave these alerts.")


class BulkCloseUndoResponse(BaseModel):
    reopened: int
    changed_since: int
    too_late: int
    not_found: int


@router.post("/bulk-close/undo", response_model=BulkCloseUndoResponse)
async def undo_bulk_close(
    body: BulkCloseUndoRequest,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: DBSession,
) -> BulkCloseUndoResponse:
    """Put alerts back the way they were before a bulk close made in the last ten minutes (a slip of the hand on 200 alerts).

    An alert is only put back when it is still exactly as the close left it: it still has the status the close gave it and it was finished within the last ten minutes. One that somebody has
    changed since is left alone and counted, as is one closed longer ago. It can only be put back to a status that is not itself finished. Each alert put back is written to the audit log.
    """
    if any(is_finished(i.status_from) for i in body.items):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An alert can only be put back to a status that is not finished."
        )
    reopened = changed = late = missing = 0
    now = datetime.now(UTC)
    for item in {i.id: i for i in body.items}.values():
        try:
            async with alert_scope(db, current_user.tenant_id, item.id) as tid:
                alert = (await db.execute(select(Alert).where(Alert.id == item.id, Alert.tenant_id == tid))).scalar_one_or_none()
                if alert is None:
                    missing += 1
                    continue
                if alert.status != body.status:
                    changed += 1
                    continue
                finished_at = alert.resolved_at
                if finished_at is not None and finished_at.tzinfo is None:
                    finished_at = finished_at.replace(tzinfo=UTC)
                if finished_at is None or now - finished_at > timedelta(minutes=BULK_CLOSE_UNDO_MINUTES):
                    late += 1
                    continue
                values: dict = {"status": item.status_from, "resolved_at": None, "updated_at": now}
                if body.status == "false_positive" and alert.disposition == "false_positive":
                    values["disposition"] = None  # the verdict the close set goes with it
                await db.execute(update(Alert).where(Alert.id == item.id).values(**values))
                await emit_audit(
                    db=db,
                    tenant_id=tid,
                    actor_id=current_user.user_id,
                    action="alerts:bulk_close_undone",
                    resource="alert",
                    resource_id=str(item.id),
                    changes={"status_from": body.status, "status_to": item.status_from},
                    request=request,
                )
                reopened += 1
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            missing += 1
    await db.commit()
    return BulkCloseUndoResponse(reopened=reopened, changed_since=changed, too_late=late, not_found=missing)


class BulkAssignRequest(BaseModel):
    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assignee_id: uuid.UUID | None = Field(default=None, description="Who the alerts go to; none unassigns them.")
    note: str | None = Field(default=None, max_length=500, description="Why, kept in the audit log against each alert.")


class AssignedItem(BaseModel):
    id: uuid.UUID
    assignee_from: uuid.UUID | None = None
    assigned_at_from: datetime | None = None


class BulkAssignResponse(BaseModel):
    assigned: int
    already_finished: int
    not_found: int
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    # What was changed and who each alert belonged to before, so the assignment can be undone for a few minutes (POST /alerts/bulk-assign/undo).
    assigned_items: list[AssignedItem] = []


@router.post("/bulk-assign", response_model=BulkAssignResponse)
async def bulk_assign_alerts(
    body: BulkAssignRequest,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: DBSession,
) -> BulkAssignResponse:
    """Assign (or, with no assignee, unassign) up to 200 alerts at once, with an optional note. The assignee must be someone in the caller's own workspace. A finished alert is left as it is (and counted); one
    the caller cannot see is counted as not found. Who, from whom and the note are written to the audit log for each alert."""
    note = " ".join((body.note or "").split()) or None
    batch = uuid.uuid4().hex[:12]  # one id on every audit entry of this call
    name: str | None = None
    if body.assignee_id is not None:
        person = (
            await db.execute(
                select(User).where(User.id == body.assignee_id, User.tenant_id == current_user.tenant_id, User.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if person is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That person is not in this workspace, or is switched off.")
        name = person.email or person.account_name
    assigned = already = missing = 0
    assigned_items: list[AssignedItem] = []
    for alert_id in dict.fromkeys(body.alert_ids):
        try:
            async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
                alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
                if alert is None:
                    missing += 1
                    continue
                if alert.status in FINISHED_STATUSES:
                    already += 1
                    continue
                before = alert.assigned_to_id
                before_at = alert.assigned_at
                now = datetime.now(UTC)
                values: dict = {"assigned_to_id": body.assignee_id, "assigned_at": now if body.assignee_id else None, "updated_at": now}
                if body.assignee_id is not None and alert.first_seen_at is None:
                    values["first_seen_at"] = now  # the first time a person acted on it: what MTTA is measured to
                await db.execute(update(Alert).where(Alert.id == alert_id).values(**values))
                await emit_audit(
                    db=db,
                    tenant_id=tid,
                    actor_id=current_user.user_id,
                    action="alerts:bulk_assign",
                    resource="alert",
                    resource_id=str(alert_id),
                    changes={
                        "assignee_from": str(before) if before else None,
                        "assignee_to": str(body.assignee_id) if body.assignee_id else None,
                        "note": note,
                        "batch": batch,
                    },
                    request=request,
                )
                assigned += 1
                assigned_items.append(AssignedItem(id=alert_id, assignee_from=before, assigned_at_from=before_at))
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            missing += 1
    await db.commit()
    return BulkAssignResponse(
        assigned=assigned,
        already_finished=already,
        not_found=missing,
        assignee_id=body.assignee_id,
        assignee_name=name,
        assigned_items=assigned_items,
    )


class BulkAssignUndoRequest(BaseModel):
    items: list[AssignedItem] = Field(min_length=1, max_length=200)
    assignee_id: uuid.UUID | None = Field(description="Who the bulk assign gave these alerts to (none when it unassigned them).")


class BulkAssignUndoResponse(BaseModel):
    restored: int
    changed_since: int
    too_late: int
    not_found: int


@router.post("/bulk-assign/undo", response_model=BulkAssignUndoResponse)
async def undo_bulk_assign(
    body: BulkAssignUndoRequest,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: DBSession,
) -> BulkAssignUndoResponse:
    """Give alerts back to whoever had them before a bulk assign made in the last ten minutes.

    An alert is only put back when it is still with the person the assign gave it to (or still unassigned, if the assign unassigned it), was changed by it in the last ten minutes, and is not
    finished. One that somebody has reassigned, finished or edited since is left alone and counted. Each alert put back is written to the audit log.
    """
    restored = changed = late = missing = 0
    now = datetime.now(UTC)
    for item in {i.id: i for i in body.items}.values():
        try:
            async with alert_scope(db, current_user.tenant_id, item.id) as tid:
                alert = (await db.execute(select(Alert).where(Alert.id == item.id, Alert.tenant_id == tid))).scalar_one_or_none()
                if alert is None:
                    missing += 1
                    continue
                if alert.status in FINISHED_STATUSES or alert.assigned_to_id != body.assignee_id:
                    changed += 1
                    continue
                # When the assign happened: the time it set, or (an unassign sets none) the last change.
                moment = alert.assigned_at if body.assignee_id is not None else alert.updated_at
                if moment is not None and moment.tzinfo is None:
                    moment = moment.replace(tzinfo=UTC)
                if moment is None or now - moment > timedelta(minutes=BULK_CLOSE_UNDO_MINUTES):
                    late += 1
                    continue
                await db.execute(
                    update(Alert)
                    .where(Alert.id == item.id)
                    .values(assigned_to_id=item.assignee_from, assigned_at=item.assigned_at_from, updated_at=now)
                )
                await emit_audit(
                    db=db,
                    tenant_id=tid,
                    actor_id=current_user.user_id,
                    action="alerts:bulk_assign_undone",
                    resource="alert",
                    resource_id=str(item.id),
                    changes={
                        "assignee_from": str(body.assignee_id) if body.assignee_id else None,
                        "assignee_to": str(item.assignee_from) if item.assignee_from else None,
                    },
                    request=request,
                )
                restored += 1
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            missing += 1
    await db.commit()
    return BulkAssignUndoResponse(restored=restored, changed_since=changed, too_late=late, not_found=missing)


@router.patch("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: uuid.UUID,
    request: AlertUpdateRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:write"))],
    db: DBSession,
    http_request: Request = None,  # type: ignore[assignment]  # FastAPI injects it; None only for a direct call
) -> AlertResponse:
    """Update alert status, priority, tags, assignment, or case link. A change of status is written to the audit log, as the bulk close does."""
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))
        alert = result.scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        updates: dict = {}
        if request.status is not None:
            updates["status"] = request.status
            if request.status in ("resolved", "false_positive", "closed"):
                updates["resolved_at"] = datetime.now(UTC)
            elif alert.resolved_at is not None:
                updates["resolved_at"] = None  # reopened: it is not resolved any more, and a stale time would count it in MTTR
        if request.priority is not None:
            updates["priority"] = request.priority
        if request.tags is not None:
            updates["tags"] = request.tags
        if request.assigned_to_id is not None:
            updates["assigned_to_id"] = request.assigned_to_id
            updates["assigned_at"] = datetime.now(UTC)
        if request.case_id is not None:
            updates["case_id"] = request.case_id

        if updates:
            updates["updated_at"] = datetime.now(UTC)
            if alert.first_seen_at is None and ("assigned_at" in updates or updates.get("status", alert.status) != alert.status):
                updates["first_seen_at"] = updates["updated_at"]  # the first time a person acted on it: what MTTA is measured to
            before = alert.status
            await db.execute(update(Alert).where(Alert.id == alert_id).values(**updates))
            if "status" in updates and updates["status"] != before:
                await emit_audit(
                    db=db,
                    tenant_id=tid,
                    actor_id=current_user.user_id,
                    action="alerts:status_change",
                    resource="alert",
                    resource_id=str(alert_id),
                    changes={"status_from": before, "status_to": updates["status"]},
                    request=http_request,
                )
            await db.commit()
            await db.refresh(alert)

        return AlertResponse.model_validate(alert)


@router.post("/{alert_id}/escalate", response_model=AlertResponse)
async def escalate_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:triage"))],
    db: DBSession,
) -> AlertResponse:
    """Escalate an alert (raises severity by one level)."""
    severity_ladder = ["info", "low", "medium", "high", "critical"]

    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))
        alert = result.scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        current_idx = severity_ladder.index(alert.severity) if alert.severity in severity_ladder else 2
        new_severity = severity_ladder[min(current_idx + 1, len(severity_ladder) - 1)]

        await db.execute(update(Alert).where(Alert.id == alert_id).values(severity=new_severity, updated_at=datetime.now(UTC)))
        await db.commit()
        await db.refresh(alert)

        return AlertResponse.model_validate(alert)


@router.post("/{alert_id}/claim", response_model=AlertResponse)
async def claim_alert_endpoint(
    alert_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:triage"))],
    db: TenantDBSession,
) -> AlertResponse:
    """Atomically claim an unassigned alert for the current user.

    Returns ``409 Conflict`` if the alert is already assigned to someone
    else — the claim is a compare-and-set on ``assigned_to_id``, so two
    analysts racing for the same alert never both win.
    """
    try:
        async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
            alert = await claim_alert(
                db,
                alert_id=alert_id,
                tenant_id=tid,
                user_id=current_user.user_id,
            )
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlertAlreadyClaimedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return AlertResponse.model_validate(alert)


@router.post("/{alert_id}/snooze", response_model=AlertResponse)
async def snooze_alert(
    alert_id: uuid.UUID,
    body: AlertSnoozeRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:triage"))],
    db: TenantDBSession,
    http_request: Request = None,  # type: ignore[assignment]  # FastAPI injects it; None only for a direct call
) -> AlertResponse:
    """Defer an alert for a fixed window from the mobile responder PWA.

    Either ``duration_minutes`` or ``until`` must be supplied. The alert
    re-surfaces in the queue once ``snoozed_until`` is in the past.
    """
    from datetime import timedelta

    if body.duration_minutes is None and body.until is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either duration_minutes or until must be provided",
        )

    if body.until is not None:
        snoozed_until = body.until.astimezone(UTC) if body.until.tzinfo else body.until.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if snoozed_until <= now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="until must be in the future")
        if snoozed_until > now + timedelta(days=30):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="until must be within 30 days")
    else:
        if (body.duration_minutes or 0) <= 0 or (body.duration_minutes or 0) > 60 * 24 * 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="duration_minutes must be between 1 and 43200 (30 days)",
            )
        snoozed_until = datetime.now(UTC) + timedelta(minutes=body.duration_minutes or 0)

    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        result = await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))
        alert = result.scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        await db.execute(
            update(Alert)
            .where(Alert.id == alert_id)
            .values(
                snoozed_until=snoozed_until,
                snoozed_by_id=current_user.user_id,
                updated_at=datetime.now(UTC),
            )
        )
        # The reason has no column of its own: it is kept in the audit log against the alert.
        reason = " ".join((body.reason or "").split())
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=current_user.user_id,
            action="alerts:snooze",
            resource="alert",
            resource_id=str(alert_id),
            changes={"snoozed_until": snoozed_until.isoformat(), **({"reason": reason} if reason else {})},
            request=http_request,
        )
        await db.commit()
        await db.refresh(alert)

    return AlertResponse.model_validate(alert)
