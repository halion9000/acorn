"""Emails people the policies they have not accepted yet (Policies, Assign).

Hourly it looks at every assignment whose person has not accepted the newest version of the policy and, for each person who is due a reminder (at once when never told, then every 7 days, every 3 once the due day has
passed), sends ONE e-mail listing everything they owe with a link to My policies. A reminder is recorded only when Microsoft accepted the message, so a failure (credentials, throttling) is simply tried again the
next hour. Nothing is sent when the mail credentials are not set. At most MAX_PER_PASS people are written to in one pass; the rest follow the next hour. A failure for one person never stops the others.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import func, select

from app.core.config import settings as default_settings
from app.db.rls_sessions import platform_session, tenant_session
from app.models.governance import GovernanceItem, GovernanceVersion
from app.models.policy_acceptance import PolicyAcceptance, PolicyAssignment
from app.services import policy_assignment as rules
from app.services import worker_heartbeat
from app.services.alert_email.graph import GraphMailer, MailError

logger = structlog.get_logger()


@dataclass(frozen=True)
class Row:
    assignment_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    name: str | None
    title: str
    due_on: date
    last_reminded_at: datetime | None
    accepted: bool


def groups_to_remind(rows: list[Row], now: datetime) -> dict[tuple[uuid.UUID, str], list[Row]]:
    """The people due a reminder and what each owes, keyed by (organization, address). A person is due when any policy they owe is due a reminder; the message then lists everything they owe (pure)."""
    owed: dict[tuple[uuid.UUID, str], list[Row]] = {}
    for r in rows:
        if not r.accepted:
            owed.setdefault((r.tenant_id, r.email), []).append(r)
    return {k: v for k, v in owed.items() if any(rules.reminder_due(r.last_reminded_at, r.due_on, now) for r in v)}


def message_for(rows: list[Row], today: date, link: str) -> tuple[str, str]:
    name = next((r.name for r in rows if r.name), None)
    return rules.reminder_message(name, [rules.Owed(r.title, r.due_on, r.due_on < today) for r in rows], link)


async def _load(factory: Callable[[], Any] | None) -> list[Row]:
    async with platform_session(factory=factory) as s:
        pairs = (
            await s.execute(
                select(PolicyAssignment, GovernanceItem.title)
                .join(GovernanceItem, GovernanceItem.id == PolicyAssignment.item_id)
                .where(GovernanceItem.archived_at.is_(None))
                .limit(20000)
            )
        ).all()
        if not pairs:
            return []
        item_ids = list({a.item_id for a, _ in pairs})
        newest = dict(
            (
                await s.execute(
                    select(GovernanceVersion.item_id, func.max(GovernanceVersion.version))
                    .where(GovernanceVersion.item_id.in_(item_ids))
                    .group_by(GovernanceVersion.item_id)
                )
            ).all()
        )
        accepted = {
            (a.item_id, a.email)
            for a in (await s.execute(select(PolicyAcceptance).where(PolicyAcceptance.item_id.in_(item_ids)))).scalars()
            if newest.get(a.item_id) == a.version
        }
        return [
            Row(a.id, a.tenant_id, a.email, a.display_name, title, a.due_on, a.last_reminded_at, (a.item_id, a.email) in accepted)
            for a, title in pairs
            if a.item_id in newest  # a policy with no text yet cannot be read or accepted
        ]


async def remind_once(
    *, now: datetime | None = None, factory: Callable[[], Any] | None = None, mailer: GraphMailer | None = None, link: str | None = None
) -> dict[str, int | str]:
    """One pass. Returns how many people were written to and how many failed, or why nothing was sent."""
    now = now or datetime.now(UTC)
    mailer = mailer or GraphMailer.from_settings()
    if not mailer.configured:
        return {"skipped": "not_configured", "sent": 0, "failed": 0}
    base = (default_settings.CONSOLE_PUBLIC_BASE_URL or "").strip().rstrip("/")
    link = link if link is not None else (f"{base}/my-policies" if base.lower().startswith(("http://", "https://")) else "")
    due = groups_to_remind(await _load(factory), now)
    sent = failed = 0
    for (tenant, email), owed in list(due.items())[: rules.MAX_PER_PASS]:
        subject, body = message_for(owed, now.date(), link)
        try:
            await mailer.send([email], subject, body)
        except MailError as exc:
            failed += 1
            logger.warning("policy_reminder.send_failed", permanent=exc.permanent)
            if exc.permanent:
                break  # credentials or permissions: every other message would fail the same way
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("policy_reminder.error", error=type(exc).__name__)
            continue
        sent += 1
        try:
            async with tenant_session(tenant, factory=factory) as s:
                for r in owed:
                    row = (
                        await s.execute(
                            select(PolicyAssignment).where(PolicyAssignment.id == r.assignment_id, PolicyAssignment.tenant_id == tenant)
                        )
                    ).scalar_one_or_none()
                    if row is not None:
                        row.last_reminded_at = now
                        row.reminders_sent = (row.reminders_sent or 0) + 1
                await s.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("policy_reminder.record_failed", error=type(exc).__name__)
    return {"sent": sent, "failed": failed}


async def run_policy_reminders(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(300, settings.POLICY_REMINDER_INTERVAL_SECONDS)
    worker_heartbeat.expect("policy_reminders", interval, first_turn_after_seconds=max(0, settings.POLICY_REMINDER_INITIAL_DELAY_SECONDS))
    await sleep(max(0, settings.POLICY_REMINDER_INITIAL_DELAY_SECONDS))
    while True:
        try:
            result = await remind_once(factory=factory)
            if result.get("sent") or result.get("failed"):
                logger.info("policy_reminder.pass", **result)
            worker_heartbeat.beat("policy_reminders")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("policy_reminder.loop_error", error=type(exc).__name__)
            worker_heartbeat.beat("policy_reminders", error=type(exc).__name__)
        await sleep(interval)
