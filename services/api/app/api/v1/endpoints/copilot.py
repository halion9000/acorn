"""POST /api/v1/copilot/chat — real LLM-backed analyst copilot.

Wires the CopilotDock (and eventually CopilotView) to the existing LiteLLM
gateway via the same ``make_chat_model`` / ``safe_ainvoke`` path that the
investigation pipeline already uses.  The ``aisoc-copilot`` alias is pinned
in ``model_pins.py`` and routed through whatever provider CORE's active
config points at (GhostCLI today, OpenRouter or local tomorrow).

Conversation history is persisted in Postgres (``copilot_conversations``), keyed by (tenant, owner, conversation) so follow-up questions work across restarts and a conversation id from another
tenant or user is simply an unknown id. It used to be a module-level dict keyed by the client-supplied conversationId alone: a restart silently dropped the model's memory while the UI still showed
the chat, any holder of another tenant's id could read and write that conversation, and its LRU was global so one tenant evicted everyone else's. See ``app/services/copilot_history.py``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.api.v1.deps import AuthUser, require_permission
from app.copilot_tools import (
    CONFIRMED_ACTIONS,
    COPILOT_TOOL_SCHEMAS,
    TOOL_PERMISSIONS,
    ConfirmationError,
    alert_snapshot,
    docs_snapshot,
    execute_copilot_tool,
    halo_snapshot,
    split_pending,
    verify_confirmation,
    wants_alert_data,
)
from app.db.rls import TenantDBSession
from app.llm.contract import safe_ainvoke
from app.llm.factory import llm_override, make_chat_model
from app.services import copilot_history
from app.services.copilot_textcalls import parse_text_tool_calls
from app.services.llm_resolver import LlmConfig, resolve_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot"])

# ---------------------------------------------------------------------------
# Request / response shapes — must match apps/web/src/lib/api.ts
# ---------------------------------------------------------------------------


class CopilotContext(BaseModel):
    alertId: str | None = None
    caseId: str | None = None
    entity: str | None = None
    page: str | None = None


class CopilotChatRequest(BaseModel):
    conversationId: str | None = None
    message: str = Field(..., min_length=1)
    context: CopilotContext | None = None


class CopilotMessageOut(BaseModel):
    id: str
    role: str  # "user" | "assistant"
    content: str
    createdAt: str
    suggestions: list[str] | None = None


def tenant_llm_override(config: LlmConfig) -> dict[str, str]:
    """The tenant's own model settings, for ``llm_override``; empty when the tenant has none, so the gateway alias applies as for the agents.

    The resolver keeps base URLs without the ``/v1`` the OpenAI client wants.
    """
    if not config.allowed or config.source not in ("tenant", "mixed") or not config.api_key:
        return {}
    base = config.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return {"api_key": config.api_key, "base_url": base, "model": config.model}


class PendingActionOut(BaseModel):
    """A destructive action the Copilot asked for and that is WAITING for the analyst. Nothing has happened yet. The token is for the UI's confirm call only; it is never shown to the model."""

    action: str
    summary: str
    token: str
    expiresAt: int


class CopilotChatResponse(BaseModel):
    conversationId: str
    reply: CopilotMessageOut
    degraded: bool = False
    pendingActions: list[PendingActionOut] = Field(default_factory=list)


class ConfirmActionRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=4000)


class ConfirmActionResponse(BaseModel):
    status: str  # "done" | "failed"
    action: str
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# System prompt — scoped to SOC analyst work
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are AiSOC Copilot, an AI assistant embedded in a Security Operations \
Center console. You help analysts triage alerts, investigate incidents, \
understand detection rules, and navigate the platform.

Guidelines:
- Be concise and actionable. Lead with the answer, not the reasoning.
- When referencing alerts, cases, hosts, or users, include their IDs so \
the analyst can jump to them.
- If you don't have enough context to answer, say what information would \
help rather than guessing.
- Never fabricate alert data, case details, or IOC values.
- Keep responses under 300 words unless the analyst asks for detail.
- You are also expert in HaloPSA (the MSP's ticketing and billing \
system). For any question about how Halo works or how to configure it, \
use search_halo_guides then read_halo_guide, answer from the guide, and \
give its link. Never answer Halo setup questions from memory, and say so \
when the guides do not cover something.
- For what is wrong at a client (Microsoft 365 or Google Workspace admins \
and stale accounts, failed sign-ins, leaked credentials on the dark web, \
backups, endpoint tools) call client_checks; for our own company's \
compliance (Secureframe tests, risks, policies, NIST CSF or CIS IG1 \
requirements) call secureframe_status. For "how is <client> doing" or a comparison of two clients call client_overview once per client; for "what changed" or "what got worse" call client_changes. A check a person accepted as a risk is not a problem: do not raise it again. Answer from what the tools return, and end by saying which tool and client it came from. Call the tool yourself: never offer to call it and wait for a yes.
- If the analyst's message is not about the SOC environment (a greeting, \
a question about who or what you are, small talk), answer that plainly \
and briefly. Only produce security analysis when there is real alert, \
case, or entity data to analyze — either provided in context or from a \
tool call you actually made. Never invent a hypothetical incident, alert, \
or entity to illustrate a point.
"""


def _context_snippet(ctx: CopilotContext | None) -> str:
    """Build a short context line from the current page state."""
    if ctx is None:
        return ""
    parts: list[str] = []
    if ctx.page:
        parts.append(f"Current page: {ctx.page}")
    if ctx.alertId:
        parts.append(f"Viewing alert: {ctx.alertId}")
    if ctx.caseId:
        parts.append(f"Viewing case: {ctx.caseId}")
    if ctx.entity:
        parts.append(f"Focused entity: {ctx.entity}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class ConversationSummary(BaseModel):
    id: str
    title: str
    updatedAt: datetime
    messageCount: int


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]


class StoredMessage(BaseModel):
    id: str
    role: str
    content: str
    createdAt: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[StoredMessage]


@router.get("/conversations", response_model=ConversationList, summary="The signed-in person's recent copilot conversations, newest first.")
async def list_copilot_conversations(
    user: Annotated[AuthUser, Depends(require_permission("copilot:use"))], db: TenantDBSession
) -> ConversationList:
    return ConversationList(conversations=await copilot_history.list_conversations(db, user.tenant_id, copilot_history.owner_key(user)))


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="One of the signed-in person's conversations, to carry on in the chat.",
)
async def get_copilot_conversation(
    conversation_id: str, user: Annotated[AuthUser, Depends(require_permission("copilot:use"))], db: TenantDBSession
) -> ConversationDetail:
    found = (
        await copilot_history.get_conversation(db, user.tenant_id, copilot_history.owner_key(user), conversation_id)
        if copilot_history.valid_conversation_id(conversation_id)
        else None
    )
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationDetail(**found)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete one of the signed-in person's conversations.",
)
async def delete_copilot_conversation(
    conversation_id: str, user: Annotated[AuthUser, Depends(require_permission("copilot:use"))], db: TenantDBSession
) -> None:
    removed = (
        await copilot_history.delete_conversation(db, user.tenant_id, copilot_history.owner_key(user), conversation_id)
        if copilot_history.valid_conversation_id(conversation_id)
        else False
    )
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    await db.commit()


@router.post(
    "/chat",
    response_model=CopilotChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a message to the AI copilot and get a real LLM response.",
)
async def copilot_chat(
    body: CopilotChatRequest,
    user: Annotated[AuthUser, Depends(require_permission("copilot:use"))],
    db: TenantDBSession,
) -> CopilotChatResponse:
    """Route a copilot message through the LiteLLM gateway.

    Falls back to a deterministic error message if the LLM call fails —
    the dock treats any non-2xx as demo-mode, so we always return 200
    with *something* useful even when the gateway is unreachable.
    The ``degraded`` flag in the response tells the frontend whether the
    reply came from the real model or from the fallback path.
    """
    conversation_id = body.conversationId or str(uuid.uuid4())
    if not copilot_history.valid_conversation_id(conversation_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="conversationId must be 1-100 characters from A-Z a-z 0-9 . _ : -"
        )
    owner = copilot_history.owner_key(user)
    # History is looked up by (tenant, owner, conversation), never by the client-supplied id alone.
    history = await copilot_history.load_history(db, user.tenant_id, owner, conversation_id)
    # The model the rest of the platform uses for this tenant: its own key/model from Settings when it has one, else the gateway alias.
    llm_config = await resolve_llm_config(db, user.tenant_id)
    await db.rollback()  # release the connection: the model call below can take many seconds

    # Build the full message list: system prompt + context + stored history
    # + new user message. System/context messages are NOT stored — they're
    # rebuilt per request so context changes (page navigation) take effect.
    messages: list[Any] = [SystemMessage(content=_SYSTEM_PROMPT)]
    ctx_line = _context_snippet(body.context)
    if ctx_line:
        messages.append(SystemMessage(content=f"[Analyst context]\n{ctx_line}"))
    # A question about the alerts gets the live list up front. Many models behind the gateway cannot call tools (the gateway drops the tools for them), and one that cannot says it "has no access to your alert data".
    if wants_alert_data(body.message):
        snapshot = await alert_snapshot(tenant_id=str(user.tenant_id), user=user)
        await db.rollback()
        if snapshot:
            messages.append(SystemMessage(content=snapshot))
    # A question that the clients' documentation (IT Glue) can answer gets the matching passages up front, for the same reason: a model that cannot call tools would otherwise say it has no access.
    docs = await docs_snapshot(tenant_id=str(user.tenant_id), user=user, message=body.message)
    await db.rollback()
    if docs:
        messages.append(SystemMessage(content=docs))
    # A question about Halo gets its best matching guides up front, for the same reason.
    halo = await halo_snapshot(tenant_id=str(user.tenant_id), user=user, message=body.message)
    await db.rollback()
    if halo:
        messages.append(SystemMessage(content=halo))
    messages.extend(history)
    messages.append(HumanMessage(content=body.message))

    degraded = False
    content = ""
    pending_actions: list[PendingActionOut] = []
    try:
        with llm_override(**tenant_llm_override(llm_config)):
            llm = make_chat_model("copilot", temperature=0.3, max_tokens=1024)
        bound = llm.bind_tools(COPILOT_TOOL_SCHEMAS)
        tenant_id = str(user.tenant_id)
        max_tool_iters = 6
        for _iteration in range(max_tool_iters):
            result = await safe_ainvoke(bound, messages)
            messages.append(result)
            tool_calls = getattr(result, "tool_calls", None) or []
            if not tool_calls:
                content = getattr(result, "content", "") or ""
                # A model that cannot call tools may WRITE the call as text (a ```tool_use block): run it, hand back the result and let the model answer, instead of showing the analyst the block.
                text_calls = parse_text_tool_calls(content) if _iteration < max_tool_iters - 1 else []
                if text_calls:
                    for name, args in text_calls:
                        shown = await execute_copilot_tool(name, args, str(user.tenant_id), user=user)
                        messages.append(
                            HumanMessage(
                                content=(
                                    f"[Result of {name}]\n{json.dumps(shown, default=str)[:4000]}\n"
                                    "[Answer the analyst's question from this result. Do not write another tool call unless you need one more.]"
                                )
                            )
                        )
                    continue
                break
            for call in tool_calls:
                name = call.get("name", "")
                args = call.get("args", {}) or {}
                call_id = call.get("id", "") or ""
                tool_result = await execute_copilot_tool(name, args, tenant_id, user=user)
                # A destructive tool only REQUESTED its action: the signed confirmation goes to the analyst's UI and is removed from what the model is shown.
                tool_result, pending = split_pending(tool_result)
                if pending and len(pending_actions) < 5:
                    pending_actions.append(PendingActionOut(**pending))
                messages.append(
                    ToolMessage(
                        content=json.dumps(tool_result, default=str)[:4000],
                        tool_call_id=call_id,
                    )
                )
        else:
            content = getattr(result, "content", "") or ""
            # (This used structlog-style keyword arguments on a STDLIB logger, which raises TypeError: the warning itself crashed, the outer except caught it, and a model that was working was reported
            # to the analyst as "couldn't reach the LLM backend".)
            logger.warning("copilot.tool_loop.truncated iterations=%s", max_tool_iters)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Copilot LLM call failed: %s", exc, exc_info=True)
        degraded = True
        content = (
            "I couldn't reach the LLM backend right now. "
            "Check that the LiteLLM gateway is running and that CORE's "
            "provider config is synced (rebuild AISOC or run "
            "`syncAisocProviderConfig()` from the HUD)."
        )

    # Store this turn in conversation history — but only if the LLM call
    # actually succeeded. Storing fallback apologies as real assistant turns
    # would poison future context when the gateway recovers.
    if not degraded:
        try:
            await copilot_history.append_turn(db, user.tenant_id, owner, conversation_id, body.message, content)
        except Exception:  # noqa: BLE001
            # The analyst still gets the answer they waited for; only the stored context for their NEXT message is lost.
            logger.warning("copilot.history.save_failed conversation=%s", conversation_id, exc_info=True)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    reply = CopilotMessageOut(
        id=str(uuid.uuid4()),
        role="assistant",
        content=content,
        createdAt=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
        suggestions=None,
    )

    return CopilotChatResponse(conversationId=conversation_id, reply=reply, degraded=degraded, pendingActions=pending_actions)


_CONFIRM_ERRORS = {
    "malformed": (400, "That confirmation is not valid."),
    "signature": (400, "That confirmation is not valid."),
    "unknown_action": (400, "That confirmation is not valid."),
    "expired": (410, "That confirmation has expired. Ask Leafy again."),
    "wrong_tenant": (403, "That confirmation was not issued to you."),
    "wrong_user": (403, "That confirmation was not issued to you."),
}


@router.post(
    "/actions/confirm",
    response_model=ConfirmActionResponse,
    summary="Confirm a destructive action the Copilot asked for",
)
async def confirm_action(
    body: ConfirmActionRequest,
    user: Annotated[AuthUser, Depends(require_permission("copilot:use"))],
) -> ConfirmActionResponse:
    """Perform a destructive action the Copilot REQUESTED, after the analyst approved it.

    This is the only way such an action happens, and it is not a model tool: the model cannot call it. The token must have been issued to THIS user in THIS tenant, must not have expired, and its signature must verify; the user then needs the same permission the
    matching REST endpoint requires (alerts:delete for an alert), checked here at confirmation time, not only when the request was made."""
    try:
        data = verify_confirmation(body.token, tenant_id=str(user.tenant_id), user_id=str(user.user_id))
    except ConfirmationError as exc:
        code, message = _CONFIRM_ERRORS.get(exc.reason, (400, "That confirmation is not valid."))
        raise HTTPException(status_code=code, detail=message) from exc
    action = data["a"]
    user.require_permission(TOOL_PERMISSIONS[action])
    result = await CONFIRMED_ACTIONS[action](tenant_id=str(user.tenant_id), **data["args"])
    logger.info("copilot.action.confirmed action=%s tenant=%s user=%s ok=%s", action, user.tenant_id, user.user_id, "error" not in result)
    return ConfirmActionResponse(status="failed" if "error" in result else "done", action=action, result=result)
