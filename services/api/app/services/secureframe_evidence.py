"""Our own organization's control health, brought over from Secureframe.

CORE reads Secureframe for Live Oak itself and sends, for NIST CSF 2.0 and CIS IG1, each requirement's verdict (healthy, unhealthy, not_tested, not_applicable) and the tests behind it. A.C.O.R.N works control
health out from the evidence it holds, so each verdict becomes one evidence record for that control: a healthy requirement is accepted evidence (dated when the report was read, so it ages like any other), an unhealthy
one is rejected evidence, and a requirement Secureframe has not tested (or that does not apply) leaves the control as it is.

Only records this module made are ever replaced (they carry ``raw_payload.source = "secureframe"``): a person's own evidence is never touched, and a control a person rejected stays unhealthy whatever Secureframe says.
The other frameworks (SOC 2, ISO 27001, PCI DSS, HIPAA) are not in what CORE sends, so their health still comes from hand-entered evidence.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.services import compliance_catalog

# Secureframe's framework key -> A.C.O.R.N's.
FRAMEWORKS = {"NIST_CSF_2": "NIST-CSF", "CIS_IG1": "CIS-IG1"}
SOURCE = "secureframe"


def evidence_rows(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The evidence records for a report's requirements (pure). Only requirements that are in A.C.O.R.N's catalog for that framework, and only healthy or unhealthy ones, become records."""
    known = {
        fw: {control for _group, control, _title in compliance_catalog.CATALOGS[fw]}
        for fw in FRAMEWORKS.values()
        if fw in compliance_catalog.CATALOGS
    }
    out: list[dict[str, Any]] = []
    for r in requirements:
        framework = FRAMEWORKS.get(str(r.get("framework")))
        key = str(r.get("key") or "")
        health = str(r.get("health") or "").lower()
        if framework is None or key not in known.get(framework, set()) or health not in ("healthy", "unhealthy"):
            continue
        passing = sum(int(c.get("passing") or 0) for c in r.get("controls") or [])
        failing = sum(int(c.get("failing") or 0) for c in r.get("controls") or [])
        out.append(
            {
                "framework": framework,
                "control_id": key,
                "control_title": str(r.get("title") or "")[:300] or None,
                "status": "accepted" if health == "healthy" else "rejected",
                "summary": f"Secureframe says this requirement is {health} ({passing} test{'' if passing == 1 else 's'} passing, {failing} failing).",
                "payload": {"source": SOURCE, "health": health, "passing": passing, "failing": failing},
            }
        )
    return out


async def sync(db: Any, tenant_id: Any, requirements: list[dict[str, Any]], now: datetime) -> dict[str, int]:
    """Replace the records this module made for the tenant with the ones for the report, leaving every other record alone. Returns how many records were written."""
    rows = evidence_rows(requirements)
    await db.execute(
        text("DELETE FROM aisoc_compliance_evidence WHERE tenant_id = :t AND raw_payload ->> 'source' = :s"),
        {"t": tenant_id, "s": SOURCE},
    )
    for r in rows:
        await db.execute(
            text(
                """
                INSERT INTO aisoc_compliance_evidence
                    (tenant_id, framework, control_id, control_title, evidence_kind, summary, raw_payload, collected_at, reviewed_by, reviewed_at, status)
                VALUES (:t, :f, :c, :title, 'other', :summary, CAST(:payload AS JSONB), :now, 'Secureframe', :now, :status)
                """
            ),
            {
                "t": tenant_id,
                "f": r["framework"],
                "c": r["control_id"],
                "title": r["control_title"],
                "summary": r["summary"],
                "payload": json.dumps(r["payload"]),
                "now": now,
                "status": r["status"],
            },
        )
    return {"written": len(rows)}
