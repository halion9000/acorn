"""The customer-facing dashboard (/client-portal): who may reach it, which HaloPSA client a signed-in customer is, and what they may be shown.

THE RULES (each has a test in tests/test_client_portal.py):
1. A person with the ``client_viewer`` role can reach ONLY the routes in ``ALLOWED_PATHS`` (the portal summary and their own sign-in and authenticator-app routes). ``enforce_reach`` is called from
   ``get_current_user``, the one dependency every signed-in route goes through, so a route that only asks "who is this?" and checks no permission is refused too. It does not depend on any route remembering to check.
2. Which client they are comes from the database, never from the request: their tenant (from their signed token and user row) is looked up in ``client_aliases`` (HaloPSA, mapped, not ignored). Nothing in the URL,
   query or headers names a client.
3. The numbers are filtered to that one client with an exact match. A client whose name cannot be matched safely (empty, or the same as another client's once case and punctuation are ignored) gets no hours or
   satisfaction rather than somebody else's.
4. The summary is served only to a person who has an authenticator app set up (``mfa_enabled``); sign-in asks for its code whenever one is set up (app/api/v1/endpoints/auth.py).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from app.db.rls_scope import cross_tenant_reads
from app.models.client_alias import ClientAlias
from app.models.finance_profit import FinanceProfitSnapshot
from app.models.tenant import Tenant
from app.models.ticket_stats import CsatSnapshot, TicketStatsSnapshot
from app.services import ticket_metrics as tm

CLIENT_VIEWER_ROLE = "client_viewer"
AUDITOR_ROLE = "auditor"
VENDOR = "halopsa"
VIEW_AS_HEADER = "x-view-as-tenant"

# The only routes a client_viewer may call (the path after /api/v<n>). Exact matches. The portal itself; ending the session; renewing it; changing their own password; and setting up the authenticator app the
# portal insists on. NOT here: /auth/totp/disable (they cannot turn the second factor off themselves; their provider can reset it), /auth/me/preferences, passkeys, push, api keys, tenants, anything else.
ALLOWED_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/client-portal/summary"),
        ("GET", "/auth/me"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/password"),
        ("GET", "/auth/totp"),
        ("POST", "/auth/totp/enrol"),
        ("POST", "/auth/totp/confirm"),
    }
)
_API_PREFIX = re.compile(r"^/api/v\d+")


def relative_path(path: str) -> str:
    """The route path without the /api/v<n> prefix and without a trailing slash."""
    rel = _API_PREFIX.sub("", path or "", count=1)
    return rel.rstrip("/") or "/"


def reach_allowed(method: str, path: str) -> bool:
    return (method.upper(), relative_path(path)) in ALLOWED_PATHS


# What an auditor may call besides /audit-portal: ending and renewing the session, changing their own password, and the authenticator app (which the audit pages insist on).
_AUDITOR_SESSION_PATHS: frozenset[tuple[str, str]] = ALLOWED_PATHS - {("GET", "/client-portal/summary")}


def auditor_reach_allowed(method: str, path: str) -> bool:
    rel = relative_path(path)
    return rel.startswith("/audit-portal/") or (method.upper(), rel) in _AUDITOR_SESSION_PATHS


def enforce_reach(role: str, request: Request | None) -> None:
    """403 for a client_viewer asking for anything outside ``ALLOWED_PATHS`` (also when the request names another tenant to view). A direct call with no request is not an HTTP request and is left alone."""
    if request is not None and role == AUDITOR_ROLE:
        if request.headers.get(VIEW_AS_HEADER) is not None or not auditor_reach_allowed(request.method, request.url.path):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This sign-in can only open the audits it was invited to.")
        return
    if role != CLIENT_VIEWER_ROLE or request is None:
        return
    if request.headers.get(VIEW_AS_HEADER) is not None or not reach_allowed(request.method, request.url.path):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This sign-in can only open the client dashboard.")


@dataclass(frozen=True)
class PortalClient:
    child_tenant_id: uuid.UUID
    parent_tenant_id: uuid.UUID
    client_id: str
    client_name: str


async def resolve_client(db: Any, child_tenant_id: uuid.UUID) -> PortalClient:
    """The HaloPSA client this customer tenant is mapped to, or an HTTPException saying why there is none.

    Reads the MSP's alias rows (owned by the parent tenant) inside a cross-tenant read block and filters them by the customer's own tenant id, then checks that the alias belongs to the customer's actual parent. A tenant
    mapped to more than one HaloPSA client is refused rather than shown only part of its numbers or somebody's else."""
    async with cross_tenant_reads(db):
        child = (await db.execute(select(Tenant).where(Tenant.id == child_tenant_id))).scalar_one_or_none()
        aliases = (
            (
                await db.execute(
                    select(ClientAlias).where(
                        ClientAlias.child_tenant_id == child_tenant_id,
                        ClientAlias.vendor == VENDOR,
                        ClientAlias.ignored.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
    mine = [a for a in aliases if child is not None and child.parent_tenant_id is not None and a.tenant_id == child.parent_tenant_id]
    if not mine:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Your company is not linked to a HaloPSA client yet. Ask your IT provider."
        )
    if len(mine) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your company is linked to more than one HaloPSA client. Ask your IT provider to fix the link.",
        )
    a = mine[0]
    return PortalClient(
        child_tenant_id=child_tenant_id, parent_tenant_id=a.tenant_id, client_id=str(a.vendor_client_id), client_name=a.vendor_client_name
    )


def _name_is_safe(name: str, ticket_payload: dict[str, Any], client_id: str) -> bool:
    """Hours and satisfaction are matched by NAME (their data carries no client id). Safe only when the name has letters or digits and no other client in the ticket data shares it once case and punctuation are ignored."""
    key = tm.name_key(name)
    if not key:
        return False
    return all(tm.name_key(c["client_name"]) != key for c in tm.clients_in(ticket_payload) if c["client_id"] != client_id)


async def summary(db: Any, client: PortalClient, months: int) -> dict[str, Any]:
    """The one client's tickets, hours and satisfaction for the newest ``months`` months. Nothing here takes a client from the caller: ``client`` came from ``resolve_client``."""
    if not client.client_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Your company is not linked to a HaloPSA client yet. Ask your IT provider."
        )
    parent = client.parent_tenant_id
    async with cross_tenant_reads(db):
        tickets = (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == parent))).scalar_one_or_none()
        profit = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == parent))).scalar_one_or_none()
        csat = (await db.execute(select(CsatSnapshot).where(CsatSnapshot.tenant_id == parent))).scalar_one_or_none()
    out: dict[str, Any] = {
        "client_name": client.client_name,
        "received_at": tickets.received_at if tickets else None,
        "tickets": None,
        "hours": None,
        "satisfaction": None,
    }
    if tickets is None:
        return out
    names = {str(a.get("id")): str(a.get("name") or "") for a in ((profit.payload if profit else {}).get("agents") or [])}
    out["tickets"] = tm.summarize(tickets.payload, months, client.client_id, names)
    # HaloPSA's own name for this client id (what the hours and the survey use), falling back to the name the mapping holds.
    name = next((c["client_name"] for c in tm.clients_in(tickets.payload) if c["client_id"] == client.client_id), "") or client.client_name
    if _name_is_safe(name, tickets.payload, client.client_id):
        if profit is not None:
            hours = tm.labor_hours(profit.payload, months, name)
            # Only this client's own figures: the list of every client and the per-client and per-engineer breakdowns stay out of the portal.
            out["hours"] = {k: hours[k] for k in ("months", "total_hours", "hours_per_month", "by_month", "by_type")}
        if csat is not None:
            out["satisfaction"] = tm.csat_for(csat.payload, months, name)
    return out
