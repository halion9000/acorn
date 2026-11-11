"""Tools a client deliberately does not use, so their absence is not reported.

Some clients will never run Huntress, ScreenConnect, Addigy or Field Effect (they use something else, or the tool does not apply). Left alone, every one of their computers is listed as "not in Huntress" on the
Devices page, the client page and the roll-ups, its tool checks fail the client's score, and a worsened check raises an alert. Excluding the tool for that client turns all of that off for that client only.

The choice is kept in the client tenant's settings (``tool_exclusions``, a list of tool names), so it needs no schema change. This module is the one place that knows the allowed names and how they are read and
written; the Devices page, the posture checks and the check alerts all ask it.
"""

from __future__ import annotations

from typing import Any

# The tools whose absence is reported as "missing", named as the Devices page names them.
EXCLUDABLE: tuple[str, ...] = ("addigy", "autoelevate", "dnsfilter", "fieldeffect", "huntress", "ninjaone", "screenconnect", "threatmate")


def of_settings(settings: Any) -> frozenset[str]:
    """The tools excluded for a client, from its tenant settings. Anything that is not a known tool name is ignored, so a hand-edited value cannot widen what is excluded."""
    raw = (settings or {}).get("tool_exclusions") if isinstance(settings, dict) else None
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(v for v in raw if isinstance(v, str) and v in EXCLUDABLE)


def normalize(vendors: list[str]) -> list[str]:
    """A request's list as it is stored: unique and sorted. Raises ValueError naming the first name that is not an excludable tool."""
    seen: set[str] = set()
    for v in vendors:
        name = (v or "").strip().lower()
        if name not in EXCLUDABLE:
            raise ValueError(name or "(empty)")
        seen.add(name)
    return sorted(seen)


def with_exclusions(settings: Any, vendors: list[str]) -> dict[str, Any]:
    """A copy of the tenant settings with the exclusions set (removed entirely when the list is empty)."""
    out = dict(settings or {})
    chosen = normalize(vendors)
    if chosen:
        out["tool_exclusions"] = chosen
    else:
        out.pop("tool_exclusions", None)
    return out


def check_is_excluded(source: str, excluded: frozenset[str]) -> bool:
    """Whether a tool check's ``source`` (``huntress``, ``threatmate-google``...) belongs to an excluded tool."""
    if not excluded:
        return False
    from app.services.infra_review import TOOL_CHECK_SOURCES  # noqa: PLC0415

    return TOOL_CHECK_SOURCES.get(source, source) in excluded


# ---- the reverse: marked as not used, but it is there ----------------------------------------------------------------------------------------------------

RULE_ID = "aisoc-tool-excluded-but-present"
RULE_NAME = "Tool marked as not used is reporting"


def detect_excluded_but_present(
    tenant_id: Any, client_name: str | None, excluded: frozenset[str], devices_by_tool: dict[str, int], mapped_tools: set[str], now: Any
) -> list[Any]:
    """A finding for each tool marked as not used for a client while the tool is in fact there: it reports devices for the client, or the client is linked to one of its organizations. Either the mark is
    wrong (untick it and the machines count again) or a tool nobody expected is installed, which is worth knowing. One finding per tool per month, so it comes back monthly while nothing is done and not daily."""
    from app.services.identity_detections import Finding  # noqa: PLC0415

    out: list[Any] = []
    stamp = now.strftime("%Y-%m")
    for tool in sorted(excluded):
        devices = devices_by_tool.get(tool, 0)
        linked = tool in mapped_tools
        if devices == 0 and not linked:
            continue
        who = client_name or "this client"
        facts = []
        if devices:
            facts.append(f"reports {devices} device{'' if devices == 1 else 's'}")
        if linked:
            facts.append("is linked to one of its organizations")
        out.append(
            Finding(
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                title=f"{tool} is marked as not used for {who}, but it is there",
                severity="medium",
                tactic="Defense Evasion",
                technique="T1562",
                key=f"{tool}:{stamp}",
                occurred_at=now,
                summary=(
                    f"{tool} is marked as not used for {who}, so its machines are not counted as missing from it and its checks are left out. But {tool} {' and '.join(facts)}. "
                    "Either the mark is wrong (untick it on the client's posture page so its machines and checks count again) or a tool nobody expected is installed there."
                ),
                fields=[("Tool", tool), ("Devices reporting", str(devices)), ("Linked to an organization", "yes" if linked else "no")],
                source_ids=[],
            )
        )
    return out


async def run_excluded_present(db: Any, owner: Any, tenant_ids: list[Any], now: Any = None) -> int:
    """Check each client for a tool that is marked as not used but is reporting, and raise the alerts. Returns how many were new. Never raises: it must not fail the sync or the change that triggered it."""
    import logging  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from sqlalchemy import distinct, func, select  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    from app.db.rls_scope import acting_as_tenant  # noqa: PLC0415
    from app.models.alert import Alert  # noqa: PLC0415
    from app.models.client_alias import ClientAlias  # noqa: PLC0415
    from app.models.device import DeviceSource  # noqa: PLC0415
    from app.models.tenant import Tenant  # noqa: PLC0415
    from app.services.identity_detections import alert_values  # noqa: PLC0415

    now = now or datetime.now(UTC)
    made = 0
    try:
        rows = (await db.execute(select(Tenant.id, Tenant.name, Tenant.settings).where(Tenant.id.in_(tenant_ids)))).all()
        for row in rows:
            excluded = of_settings(row.settings)
            if not excluded:
                continue
            aliases = (
                (
                    await db.execute(
                        select(ClientAlias.vendor).where(
                            ClientAlias.tenant_id == owner, ClientAlias.child_tenant_id == row.id, ClientAlias.ignored.is_(False)
                        )
                    )
                )
                .scalars()
                .all()
            )
            async with acting_as_tenant(db, row.id):
                counts = dict(
                    (
                        await db.execute(
                            select(DeviceSource.vendor, func.count(distinct(DeviceSource.device_id)))
                            .where(DeviceSource.tenant_id == row.id, DeviceSource.vendor.in_(excluded))
                            .group_by(DeviceSource.vendor)
                        )
                    ).all()
                )
                findings = detect_excluded_but_present(
                    row.id, row.name, excluded, {k: int(v) for k, v in counts.items()}, set(aliases) & set(excluded), now
                )
                async with db.begin_nested():
                    for f in findings:
                        values = alert_values(row.id, f, now)
                        values.update(
                            category="posture",
                            connector_type="aisoc-checks",
                            tags=["posture-change", "tool-exclusion", RULE_ID],
                            raw_event={"source": "aisoc-checks", "finding": {"uid": f"{RULE_ID}:{f.key}", "title": f.title}},
                        )
                        res = await db.execute(pg_insert(Alert).values(**values).on_conflict_do_nothing(index_elements=["id"]))
                        made += res.rowcount or 0
    except Exception:  # noqa: BLE001
        logging.getLogger("aisoc.tool_exclusions").warning("excluded-but-present check failed", exc_info=True)
        return 0
    return made
