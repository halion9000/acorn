"""One line in the audit log for a change made in the Compliance, Settings roadmap and vendor pages, so who changed what is on record.

The audit log is hash-chained and append-only (``services/audit.py``). The caller still owns the transaction: call this before the commit that makes the change, so the change and its record stand or fall together.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.services.audit import emit_audit


async def note(db: Any, tenant: uuid.UUID, user: Any, action: str, resource: str, resource_id: Any, **changes: Any) -> None:
    """Record ``action`` (for example ``access_review:completed``) by ``user`` on one resource, with the facts that matter in ``changes`` (never a secret)."""
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=getattr(user, "user_id", None),
        actor_email=getattr(user, "email", None),
        action=action,
        resource=resource,
        resource_id=str(resource_id),
        changes={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in changes.items()},
    )
