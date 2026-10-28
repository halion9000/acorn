"""Copilot tool registry — analyst-facing tools for the chat endpoint.

Wraps real DB operations (search/list/get/delete alerts and cases) as
LLM-callable tools with tenant isolation enforced at every call site.
Each tool function obtains its own DB session via AsyncSessionLocal and
sets RLS context from the authenticated user's tenant_id before executing
any query, matching the pattern used by TenantDBSession in deps.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.rls import set_rls_context
from app.db.rls_sessions import mark_tenant
from app.models.alert import Alert


def _like_pattern(query: str) -> str:
    """A substring pattern for ILIKE with %, _ and the escape character escaped, so a model-supplied `%` matches a literal percent instead of turning the search into a wildcard scan (pair with escape="\\")."""
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


logger = logging.getLogger(__name__)


async def _get_session(tenant_id: uuid.UUID) -> AsyncSession:
    """Create a tenant-scoped session outside FastAPI DI."""
    session = AsyncSessionLocal()
    mark_tenant(session, tenant_id)  # set_rls_context below lasts one transaction; the tag keeps the tenant across commits (step 4b)
    await set_rls_context(session, tenant_id)
    return session


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_CLOSED_STATUSES = ("resolved", "closed", "false_positive")


async def _scope_tenants(tid: uuid.UUID) -> list[tuple[uuid.UUID, str | None]]:
    """The caller's own tenant and each of its client tenants, as ``(id, client name)`` (the name is None for the caller's own): an MSP's alerts live under its clients."""
    from app.models.tenant import Tenant

    async with await _get_session(tid) as db:
        rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == tid))).all()
    return [(tid, None), *[(r.id, r.name) for r in rows]]


async def search_alerts(
    *,
    tenant_id: str,
    query: str = "",
    limit: int = 10,
    severity: str | None = None,
    hours: int | None = None,
    only_open: bool = False,
) -> dict[str, Any]:
    """Search alerts across this tenant and its clients, worst first then newest.

    ``query`` is a title/description substring (may be empty), ``severity`` one level, ``hours`` how far back, ``only_open`` leaves out resolved, closed and false-positive ones.
    """
    from datetime import UTC, datetime, timedelta

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        return {"error": "invalid tenant_id"}
    wanted = (severity or "").strip().lower() or None
    if wanted is not None and wanted not in _SEVERITY_ORDER:
        return {"error": f"severity must be one of {', '.join(_SEVERITY_ORDER)}"}
    cap = max(1, min(int(limit or 10), 50))
    since = datetime.now(UTC) - timedelta(hours=max(1, min(int(hours), 24 * 365))) if hours else None

    found: list[dict[str, Any]] = []
    for scope_id, client in await _scope_tenants(tid):
        async with await _get_session(scope_id) as db:
            stmt = select(Alert).where(Alert.tenant_id == scope_id)
            if query:
                pattern = _like_pattern(query)
                stmt = stmt.where(Alert.title.ilike(pattern, escape="\\") | Alert.description.ilike(pattern, escape="\\"))
            if wanted:
                stmt = stmt.where(Alert.severity == wanted)
            if since is not None:
                stmt = stmt.where(Alert.created_at >= since)
            if only_open:
                stmt = stmt.where(Alert.status.notin_(_CLOSED_STATUSES))
            alerts = (await db.execute(stmt.order_by(Alert.created_at.desc()).limit(cap))).scalars().all()
            found.extend(
                {
                    "id": str(a.id),
                    "title": a.title,
                    "severity": a.severity,
                    "status": a.status,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    **({"client": client} if client else {}),
                }
                for a in alerts
            )
    found.sort(
        key=lambda a: (
            _SEVERITY_ORDER.get(str(a["severity"]).lower(), 5),
            -(datetime.fromisoformat(a["created_at"]).timestamp() if a["created_at"] else 0),
        )
    )
    return {"count": len(found[:cap]), "alerts": found[:cap]}


_ALERT_WORDS = (
    "alert",
    "critical",
    "high severity",
    "triage",
    "incident",
    "detection",
    "case",
    "escalat",
    "what happened",
    "summar",
    "last 24",
    "today",
    "this week",
    "investigate",
)


def wants_alert_data(message: str) -> bool:
    """True when a message is probably about the alerts themselves, so the live list is put in front of the model instead of hoping it calls a tool (a model that cannot call tools says it has no access)."""
    text_ = (message or "").lower()
    return any(w in text_ for w in _ALERT_WORDS)


def format_alert_snapshot(result: dict[str, Any], hours: int) -> str:
    """The alerts found, as lines a model can quote: id, severity, status, client, title. Nothing invented: an empty result says there are none."""
    alerts = result.get("alerts") or []
    if not alerts:
        return f"[Live data] No open alerts were raised in the last {hours} hours."
    lines = [
        f"[Live data] The {len(alerts)} most severe open alert(s) from the last {hours} hours, worst first (fetched just now from the platform):"
    ]
    for a in alerts:
        client = f" | client: {a['client']}" if a.get("client") else ""
        lines.append(f"- {a['id']} | {a['severity']} | {a['status']}{client} | {str(a['title'])[:140]}")
    return "\n".join(lines)


async def alert_snapshot(*, tenant_id: str, user: Any, hours: int = 24, limit: int = 10) -> str | None:
    """The live open alerts of the last ``hours`` hours across the tenant and its clients, as text for the model, or None when the caller may not read alerts or the lookup failed."""
    result = await execute_copilot_tool("search_alerts", {"hours": hours, "only_open": True, "limit": limit}, tenant_id, user=user)
    if not isinstance(result, dict) or "error" in result:
        return None
    return format_alert_snapshot(result, hours)


async def search_client_docs(*, tenant_id: str, query: str, limit: int = 6) -> dict[str, Any]:
    """Search the clients' documentation: the organization's own and every client's, best match first. A query that names a client looks only in that client's."""
    from app.api.v1.endpoints.client_documents import find

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        return {"error": "invalid tenant_id"}
    if not query or not query.strip():
        return {"error": "query is required"}
    async with await _get_session(tid) as db:
        hits = await find(db, tid, query, None, max(1, min(int(limit or 6), 15)))
    return {
        "results": [h.model_dump(mode="json", exclude={"client_id"}) for h in hits],
        "count": len(hits),
        **(
            {}
            if hits
            else {
                "note": "Nothing in the synced documentation matches. It may not be documented, or the documentation may not be synced for that client yet."
            }
        ),
    }


def format_docs_snapshot(results: list[dict[str, Any]]) -> str | None:
    """The matching documentation as text for the model, or None when nothing matched."""
    if not results:
        return None
    lines = [
        "[Client documentation: passages from IT Glue that match the question. Answer from them when they apply and name the document; if they do not answer the question, say the documentation does not cover it. Do not invent what a document says.]"
    ]
    for r in results:
        where = f"{r['client']}: " if r.get("client") else ""
        link = f" {r['url']}" if r.get("url") else ""
        if r.get("kind") == "password":
            # Only the entry's name, user name and link are held, never the password: say so, so the model points at the link and does not guess.
            lines.append(
                f"- {where}{r['title']} (a password entry in IT Glue; the password itself is masked there, open the link to reveal it){link}\n  {r['snippet']}"
            )
            continue
        lines.append(f"- {where}{r['title']} ({r['kind']}){link}\n  {r['snippet']}")
    return "\n".join(lines)


async def docs_snapshot(*, tenant_id: str, user: Any, message: str, limit: int = 5) -> str | None:
    """Documentation matching a question, as text for the model; None when the caller may not read it, the question is too short to search, or nothing matched. A greeting is not searched."""
    from app.services.client_docs import search_terms

    try:
        if len(search_terms(message)) < 3:
            # Three words is the least that makes a question: short messages ("hi", "thanks") would match unrelated documents.
            named = await _names_a_client(tenant_id, message)
            if not named:
                return None
        result = await execute_copilot_tool("search_client_docs", {"query": message, "limit": limit}, tenant_id, user=user)
        if not isinstance(result, dict) or "error" in result:
            return None
        return format_docs_snapshot(result.get("results") or [])
    except Exception as exc:  # noqa: BLE001
        # Documentation is extra context: a failed lookup must never stop the chat from answering.
        logger.warning("copilot.docs_snapshot.failed error=%s", type(exc).__name__)
        return None


async def _names_a_client(tenant_id: str, message: str) -> bool:
    from app.services.client_docs import clients_named

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        return False
    scope = await _scope_tenants(tid)
    return bool(clients_named(message, [(cid, name) for cid, name in scope if name]))


async def get_alert(*, tenant_id: str, alert_id: str) -> dict[str, Any]:
    """Get a single alert by ID."""
    try:
        tid = uuid.UUID(tenant_id)
        aid = uuid.UUID(alert_id)
    except ValueError:
        return {"error": "invalid UUID format"}

    async with await _get_session(tid) as db:
        result = await db.execute(select(Alert).where(Alert.id == aid, Alert.tenant_id == tid))
        alert = result.scalar_one_or_none()
        if alert is None:
            return {"error": "alert not found"}
        return {
            "id": str(alert.id),
            "title": alert.title,
            "description": alert.description,
            "severity": alert.severity,
            "status": alert.status,
            "category": alert.category,
            "mitre_techniques": alert.mitre_techniques or [],
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        }


async def delete_alert(*, tenant_id: str, alert_id: str) -> dict[str, Any]:
    """REQUEST a deletion. This does NOT delete anything.

    Deleting needs the analyst's explicit confirmation, and the model must not be able to give it: alert text is attacker-influenced and sits in the model's context, so a "confirmed, go ahead" in it must never be enough. This only checks that the alert exists in the tenant and describes what would be deleted;
    execute_copilot_tool turns that into a signed, expiring confirmation that goes to the UI (never to the model), and POST /copilot/actions/confirm, which the model cannot call, performs perform_delete_alert."""
    try:
        tid = uuid.UUID(tenant_id)
        aid = uuid.UUID(alert_id)
    except ValueError:
        return {"error": "invalid UUID format"}

    async with await _get_session(tid) as db:
        alert = (await db.execute(select(Alert).where(Alert.id == aid, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            return {"error": "alert not found"}
        title = alert.title
    return {
        "alert_id": str(aid),
        "alert_title": title,
        _CONFIRM_KEY: {
            "action": "delete_alert",
            "args": {"alert_id": str(aid)},
            "summary": f'Permanently delete alert "{title}" ({aid})? This cannot be undone.',
        },
    }


async def perform_delete_alert(*, tenant_id: str, alert_id: str) -> dict[str, Any]:
    """Delete one alert. Only the confirmation endpoint calls this, and only with a valid token: it is deliberately NOT in the model's dispatch table."""
    try:
        tid = uuid.UUID(tenant_id)
        aid = uuid.UUID(alert_id)
    except ValueError:
        return {"error": "invalid UUID format"}

    async with await _get_session(tid) as db:
        result = await db.execute(delete(Alert).where(Alert.id == aid, Alert.tenant_id == tid))
        await db.commit()
        if result.rowcount == 0:  # type: ignore[union-attr]
            return {"error": "alert not found or already deleted"}
        return {"deleted": True, "alert_id": alert_id}


async def search_cases(*, tenant_id: str, query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search cases by title substring match.

    Cases live in aisoc_cases (what the cases API reads and writes). This used to read the old `cases` table, which nothing writes, so the Copilot always answered "no cases found"."""
    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        return {"error": "invalid tenant_id"}

    async with await _get_session(tid) as db:
        where_clauses = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(tid), "limit": max(1, min(limit, 50))}
        if query:
            where_clauses.append("title ILIKE :pattern ESCAPE '\\'")
            params["pattern"] = _like_pattern(query)
        sql = f"""
            SELECT id, case_number, title, status, severity, created_at
            FROM aisoc_cases
            WHERE {' AND '.join(where_clauses)}
            ORDER BY created_at DESC
            LIMIT :limit
        """
        result = await db.execute(text(sql).bindparams(**params))
        rows = result.fetchall()
        return {
            "count": len(rows),
            "cases": [
                {
                    "id": str(r.id),
                    "case_number": r.case_number,
                    "title": r.title,
                    "status": r.status,
                    "severity": r.severity,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }


async def delete_case(*, tenant_id: str, case_id: str) -> dict[str, Any]:
    """Cases cannot be deleted from the Copilot.

    This used to run `DELETE FROM cases`, the old table nothing writes, so it always answered "case not found or already deleted". Pointing it at aisoc_cases would have switched on a destructive tool that has never worked, for a model that reads
    attacker-influenced alert text, while the cases API itself has no delete (cases hold investigation evidence). So it refuses, truthfully, until deleting a case is a deliberate product decision with a confirmation step."""
    return {
        "error": "Deleting cases is not supported. A case holds investigation evidence and the cases API has no delete; close or resolve it instead."
    }


# ---------------------------------------------------------------------------
# Tool schemas for LLM binding (OpenAI function-calling format)
# ---------------------------------------------------------------------------

COPILOT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_alerts",
            "description": "Search alerts across this organisation and its clients, worst first. Filter by severity, how many hours back, and open only. Returns alerts with IDs and the client each belongs to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to match against alert titles and descriptions. Leave empty to list alerts by severity and recency.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low", "info"],
                        "description": "Only alerts of this severity.",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "Only alerts raised in the last this-many hours (for example 24).",
                    },
                    "only_open": {
                        "type": "boolean",
                        "description": "Leave out alerts that are resolved, closed or marked false positive.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10, max 50).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_client_docs",
            "description": "Search the clients' documentation (IT Glue documents, runbooks, onboarding guides, configurations) for a question or keywords. Use it for how a client is set up, what a client's procedure or guide says, or where something is documented. Put the client's name in the query to look only at that client. Returns the best matches with a passage, the client and a link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or keywords, including the client's name when it is about one client.",
                    },
                    "limit": {"type": "integer", "description": "Maximum number of results (default 6, max 15)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alert",
            "description": "Get full details of a single alert by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "The UUID of the alert to retrieve.",
                    },
                },
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_alert",
            "description": "Ask to permanently delete an alert by its ID. This does NOT delete it: the analyst is shown a confirmation prompt and must approve it. After calling this, tell the analyst that a confirmation is waiting for them and that nothing has been deleted yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "string",
                        "description": "The UUID of the alert to delete.",
                    },
                },
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_cases",
            "description": "Search cases by title keyword. Returns matching cases with IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword to match against case titles.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10, max 50).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_case",
            "description": "Not supported: cases cannot be deleted from the Copilot. To finish with a case, close or resolve it instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "string",
                        "description": "The UUID of the case to delete.",
                    },
                },
                "required": ["case_id"],
            },
        },
    },
]

# Dispatch table mapping tool names to their async implementations
_COPILOT_TOOL_DISPATCH: dict[str, Any] = {
    "search_alerts": search_alerts,
    "search_client_docs": search_client_docs,
    "get_alert": get_alert,
    "delete_alert": delete_alert,
    "search_cases": search_cases,
    "delete_case": delete_case,
}


# --- Confirmation of destructive actions -------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# A tool that changes or destroys data only REQUESTS the action. The request is turned into a token that is signed (HMAC over the tenant, user, action, arguments and expiry, keyed from SECRET_KEY under a purpose label so it can never be used as, or confused with, any other token) and expires. The token is
# removed from what the model sees and handed to the UI, which asks the analyst; only the analyst's own authenticated call to POST /copilot/actions/confirm presents it. Replaying a token inside its lifetime is harmless: the actions are idempotent ("already deleted").
_CONFIRM_KEY = "_confirm"
PENDING_KEY = "_pending"
CONFIRMATION_TTL_SECONDS = 300


def _confirmation_key() -> bytes:
    return hashlib.sha256(b"aisoc-copilot-confirm-v1:" + settings.SECRET_KEY.encode("utf-8")).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text_: str) -> bytes:
    return base64.urlsafe_b64decode(text_ + "=" * (-len(text_) % 4))


def issue_confirmation(
    *, tenant_id: str, user_id: str, action: str, args: dict[str, Any], now: float | None = None, ttl: int = CONFIRMATION_TTL_SECONDS
) -> tuple[str, int]:
    """A signed confirmation token for `action(args)` by this user in this tenant, and its expiry (epoch seconds)."""
    exp = int((time.time() if now is None else now) + ttl)
    payload = json.dumps(
        {"a": action, "args": args, "t": str(tenant_id), "u": str(user_id), "exp": exp, "n": secrets.token_hex(8)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_confirmation_key(), payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig), exp


class ConfirmationError(Exception):
    """The token is not acceptable. `reason` is one of: malformed, signature, expired, wrong_tenant, wrong_user, unknown_action."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def verify_confirmation(token: str, *, tenant_id: str, user_id: str, now: float | None = None) -> dict[str, Any]:
    """The token's payload (action, args), or ConfirmationError. The signature is checked BEFORE anything in the payload is trusted, in constant time."""
    try:
        body, sig = token.split(".", 1)
        payload = _unb64(body)
        given = _unb64(sig)
    except Exception as exc:  # noqa: BLE001
        raise ConfirmationError("malformed") from exc
    if not hmac.compare_digest(hmac.new(_confirmation_key(), payload, hashlib.sha256).digest(), given):
        raise ConfirmationError("signature")
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ConfirmationError("malformed") from exc
    if not isinstance(data, dict) or not isinstance(data.get("exp"), int) or not isinstance(data.get("args"), dict):
        raise ConfirmationError("malformed")
    if (time.time() if now is None else now) > data["exp"]:
        raise ConfirmationError("expired")
    if data.get("t") != str(tenant_id):
        raise ConfirmationError("wrong_tenant")
    if data.get("u") != str(user_id):
        raise ConfirmationError("wrong_user")
    if data.get("a") not in CONFIRMED_ACTIONS:
        raise ConfirmationError("unknown_action")
    return data


def split_pending(tool_result: Any) -> tuple[Any, dict[str, Any] | None]:
    """(what the MODEL may see, the pending confirmation for the UI or None). The token never reaches the model."""
    if isinstance(tool_result, dict) and PENDING_KEY in tool_result:
        visible = {k: v for k, v in tool_result.items() if k != PENDING_KEY}
        return visible, tool_result[PENDING_KEY]
    return tool_result, None


# The actions a confirmation token can authorise. NOT reachable from the model's tool dispatch.
CONFIRMED_ACTIONS: dict[str, Any] = {"delete_alert": perform_delete_alert}

# The permission each tool needs, the same ones the matching REST endpoints require. A tool with no entry here is not run.
TOOL_PERMISSIONS: dict[str, str] = {
    "search_alerts": "alerts:read",
    "search_client_docs": "alerts:read",
    "get_alert": "alerts:read",
    "delete_alert": "alerts:delete",
    "search_cases": "cases:read",
    "delete_case": "cases:delete",
}


async def execute_copilot_tool(name: str, args: dict[str, Any], tenant_id: str, *, user: Any) -> Any:
    """Execute a copilot tool by name, as `user`, with tenant isolation.

    The endpoint only checks `copilot:use`; this runs whatever tool the model asks for, and the tool docstrings said "Requires alerts:write" / "cases:write" while nothing enforced anything, so any user holding copilot:use (and an API key scoped to copilot:use alone)
    could have the model delete alerts. Each tool now needs the permission of the matching REST endpoint, checked exactly the way the endpoints check it (static role table, or an API key's scopes). `user` is required: omitting it fails closed.
    """
    fn = _COPILOT_TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    needed = TOOL_PERMISSIONS.get(name)
    if needed is None:
        return {"error": f"tool {name} has no declared permission and is not available"}
    if str(getattr(user, "tenant_id", "")) != str(tenant_id):
        return {"error": "tenant mismatch"}
    try:
        user.require_permission(needed)
    except HTTPException:
        return {"error": f"permission denied: {name} requires {needed}"}
    try:
        result = await fn(tenant_id=tenant_id, **(args or {}))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if isinstance(result, dict) and _CONFIRM_KEY in result:
        # A destructive tool only REQUESTED its action: sign a confirmation for the UI and tell the model, truthfully, that nothing has happened yet.
        request = result.pop(_CONFIRM_KEY)
        token, exp = issue_confirmation(
            tenant_id=str(tenant_id), user_id=str(getattr(user, "user_id", "")), action=request["action"], args=request["args"]
        )
        result["status"] = "awaiting_user_confirmation"
        result["message"] = (
            "NOTHING HAS BEEN DONE YET. The analyst has been shown a confirmation prompt and must approve it themselves. Tell them it is waiting for them; do not claim the action happened."
        )
        result[PENDING_KEY] = {"action": request["action"], "summary": request["summary"], "token": token, "expiresAt": exp}
    return result
