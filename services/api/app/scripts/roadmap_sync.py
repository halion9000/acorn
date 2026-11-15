"""Bring the roadmap up to date from docs/ROADMAP_ITEMS.json, read from standard input.

cat docs/ROADMAP_ITEMS.json | python -m app.scripts.roadmap_sync --tenant-name "Live Oak IT Partners"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.db.rls import set_rls_context
from app.db.rls_scope import cross_tenant_reads
from app.services import roadmap_sync


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-name", required=True, help="the organization whose roadmap this is")
    args = parser.parse_args()
    entries = json.loads(sys.stdin.read())
    async with AsyncSessionLocal() as db:
        async with cross_tenant_reads(db):
            rows = (await db.execute(text("select id from tenants where name = :n"), {"n": args.tenant_name})).all()
        if len(rows) != 1:
            raise SystemExit(f"expected one organization named {args.tenant_name!r}, found {len(rows)}")
        tenant = rows[0][0]
        await set_rls_context(db, tenant)
        print(await roadmap_sync.sync(db, tenant, entries))


if __name__ == "__main__":
    asyncio.run(main())
