"""At startup, put the detection rules the repository ships where people can see them: the first-party rules as built-in rules in every tenant, the imported Sigma rules in the Detection Catalog.

Both loaders are idempotent (a rule or entry that exists is left as it is), so running this on every start costs a read of the folder and nothing else once the rows exist. A failure is logged and never
stops the API: with no detections folder, or a database that is not ready, the lists stay as they were. Switch off with ``AISOC_SEED_SHIPPED_DETECTIONS=0``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

LOG = logging.getLogger(__name__)


def enabled(env: dict[str, str] | None = None) -> bool:
    return (env if env is not None else os.environ).get("AISOC_SEED_SHIPPED_DETECTIONS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


async def seed_once(session_factory: Any = None) -> dict[str, Any]:
    """Run both loaders once. Returns what each did (or why it did nothing); never raises."""
    from app.scripts import load_builtin_detections as builtin  # noqa: PLC0415
    from app.scripts import load_catalog_detections as catalog  # noqa: PLC0415

    result: dict[str, Any] = {}
    try:
        root = builtin.detections_dir()
        if root is None:
            return {"skipped": "no detections folder"}
        if session_factory is None:
            from app.db.database import AsyncSessionLocal as session_factory  # noqa: PLC0415, N813
        rules, skipped = builtin.read_rules(root)
        async with session_factory() as session:
            tenants = await builtin.list_tenant_ids(session)
        created = 0
        for tenant_id in tenants:
            async with session_factory() as session:
                report = await builtin.load(session, rules, tenant_id, skipped)
                await session.commit()
            created += report.created
        result["builtin"] = {"tenants": len(tenants), "created": created}
        entries, _ = catalog.read_entries(root)
        async with session_factory() as session:
            result["catalog"] = await catalog.load(session, entries)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - seeding is a convenience; the API starts regardless
        LOG.warning("seeding the shipped detections failed: %s", exc)
        result["error"] = str(exc)[:200]
    return result
