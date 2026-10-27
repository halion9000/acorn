"""Send a forwarded alert to the client tenant its vendor client is mapped to.

CORE forwards every tool's alerts into ONE tenant (the MSSP's own). Each record carries the vendor's id for the client it belongs to (the Huntress or NinjaOne organization,
the Petra tenant). When a person has mapped that client to one of their client tenants (MSSP page, ``client_aliases``), the alert is stored under that tenant instead, so each
customer sees only their own. A client that is not mapped, is ignored, or has no id in the record stays where it arrived: nothing is ever dropped, and a lookup failure
leaves the alert with the MSSP.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger()

# vendor -> the key in the record's context that holds that vendor's client id. Must match what CORE forwards (hud/src/aisoc-feed.ts, aisoc-ninjaone.ts) and what it lists as
# clients (hud/src/aisoc-clients.ts): Huntress organizations, Petra tenants, NinjaOne organizations, Blumira accounts, Field Effect organizations.
CLIENT_ID_FIELD: dict[str, str] = {
    "huntress": "organization_id",
    "petra": "petra_tenant_id",
    "ninjaone": "organization_id",
    "threatmate": "threatmate_client_id",
    "addigy": "addigy_client_id",
    "blumira": "blumira_account_id",
    "fieldeffect": "fieldeffect_org_id",
}

Resolver = Callable[[uuid.UUID, str, str], Awaitable[uuid.UUID | None]]
DomainResolver = Callable[[uuid.UUID, str], Awaitable[uuid.UUID | None]]

_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "edu", "ac"})
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def registrable_domain(name: object) -> str | None:
    """The domain a host name or e-mail address belongs to (``mail.example.org`` and ``a@example.org`` give ``example.org``; ``www.example.co.uk`` gives ``example.co.uk``); None for anything else, an IP address included.

    Keep in step with services/api/app/services/domain_owner.py (the API moves alerts that arrived earlier by the same rule).
    """
    text_ = str(name or "").strip().lower().rstrip(".")
    if "@" in text_:
        text_ = text_.rsplit("@", 1)[1]
    if not _HOST.match(text_):
        return None
    labels = text_.split(".")
    if not labels[-1][:1].isalpha():
        return None
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def threatmate_domain(raw_event: dict[str, Any] | None) -> str | None:
    """The registrable domain of the asset a ThreatMate alert is about (its ``device_name``: a host or an e-mail address), or None for any other tool or an asset with no domain."""
    if not isinstance(raw_event, dict) or raw_event.get("source") != "threatmate":
        return None
    unmapped = raw_event.get("unmapped")
    context = unmapped.get("context") if isinstance(unmapped, dict) else None
    device = context.get("device_name") if isinstance(context, dict) else None
    return registrable_domain(device)


def client_key(raw_event: dict[str, Any] | None) -> tuple[str, str] | None:
    """(vendor, vendor client id) of a forwarded record, or None when it names no client."""
    if not isinstance(raw_event, dict):
        return None
    vendor = raw_event.get("source")
    field = CLIENT_ID_FIELD.get(vendor) if isinstance(vendor, str) else None
    if field is None:
        return None
    unmapped = raw_event.get("unmapped")
    context = unmapped.get("context") if isinstance(unmapped, dict) else None
    value = context.get(field) if isinstance(context, dict) else None
    if isinstance(value, bool) or not isinstance(value, str | int) or str(value).strip() == "":
        return None
    return vendor, str(value).strip()


async def route_to_client_tenant(
    tenant_id: uuid.UUID,
    raw_event: dict[str, Any] | None,
    resolve: Resolver,
    resolve_domain: DomainResolver | None = None,
) -> uuid.UUID:
    """The tenant this alert should be stored under: the mapped client tenant, else ``tenant_id`` unchanged.

    ThreatMate files a client's public domain under the MSP's own segment, so its alert names the MSP as its client even when the asset belongs to a customer. For those, the domain of the
    asset (``resolve_domain``: domain -> the one client whose people use it) wins over the vendor client the alert names.
    """
    child: uuid.UUID | None = None
    key = client_key(raw_event)
    if key is not None:
        try:
            child = await resolve(tenant_id, key[0], key[1])
        except Exception as exc:  # noqa: BLE001 — a failed lookup must never lose or delay the alert
            logger.warning("client_routing.lookup_failed", error=str(exc))
            return tenant_id
    domain = threatmate_domain(raw_event) if resolve_domain is not None else None
    if domain and resolve_domain is not None:
        try:
            owner = await resolve_domain(tenant_id, domain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("client_routing.domain_lookup_failed", error=str(exc))
            owner = None
        if owner is not None:
            return owner
    return child or tenant_id
