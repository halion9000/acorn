"""Persistent copilot conversation history, scoped to (tenant, owner, conversation). Replaces a module-level dict keyed by the client-supplied conversation id alone.

What that dict got wrong (see migrations/057_copilot_conversations.sql): a restart dropped the model's memory while the UI still showed the chat; the key held no tenant or user, so another tenant's conversation id
read and wrote that conversation; and its 500-entry LRU was global, so one busy tenant evicted everyone else's conversations.

Concurrency: the model call is slow, so nothing here is held across it. load_history() reads; append_turn() takes a short row lock (SELECT ... FOR UPDATE) to append, so two messages sent to the same conversation at
once both land, in order, instead of one overwriting the other. The tenant's RLS context is transaction-local, so every operation re-asserts it rather than relying on it surviving a commit.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import set_rls_context
from app.models.copilot_conversation import CopilotConversation

MAX_MESSAGES = 40  # last N stored messages per conversation, to bound token usage
MAX_CONVERSATIONS_PER_OWNER = 200  # oldest are pruned beyond this, per (tenant, owner): one user cannot grow it without limit
MAX_STORED_CHARS = 20000  # per stored message; the model still receives the full current message
CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def valid_conversation_id(conversation_id: str) -> bool:
    return bool(CONVERSATION_ID_PATTERN.match(conversation_id))


def owner_key(user: Any) -> str:
    """Who owns the conversation: the user's id, or 'service' for a principal that has none (an API key)."""
    user_id = getattr(user, "user_id", None)
    return str(user_id) if user_id else "service"


def _to_messages(stored: list[dict[str, Any]]) -> list[BaseMessage]:
    return [
        HumanMessage(content=m["content"]) if m.get("role") == "human" else AIMessage(content=m.get("content", "")) for m in stored or []
    ]


async def load_history(db: AsyncSession, tenant_id: uuid.UUID, owner: str, conversation_id: str) -> list[BaseMessage]:
    """The stored history for THIS tenant's THIS owner's conversation. An id that belongs to someone else is simply an unknown id here: empty history, and no way to tell it exists."""
    await set_rls_context(db, tenant_id)
    row = await db.get(CopilotConversation, (tenant_id, owner, conversation_id), populate_existing=True)
    return _to_messages(row.messages if row else [])


async def append_turn(db: AsyncSession, tenant_id: uuid.UUID, owner: str, conversation_id: str, human: str, ai: str) -> None:
    """Append one successful exchange, atomically with respect to other writers of the same conversation."""
    await set_rls_context(db, tenant_id)
    key = (tenant_id, owner, conversation_id)
    row = await db.get(CopilotConversation, key, with_for_update=True, populate_existing=True)
    created = False
    if row is None:
        now = datetime.now(UTC)
        db.add(
            CopilotConversation(
                tenant_id=tenant_id, owner_key=owner, conversation_id=conversation_id, messages=[], created_at=now, updated_at=now
            )
        )
        try:
            await db.flush()
        except IntegrityError:  # another request created it between our read and our insert: take its lock instead
            await db.rollback()
            await set_rls_context(db, tenant_id)
            row = await db.get(CopilotConversation, key, with_for_update=True, populate_existing=True)
        else:
            created = True
            row = await db.get(CopilotConversation, key, with_for_update=True, populate_existing=True)
    assert row is not None
    turn = [{"role": "human", "content": human[:MAX_STORED_CHARS]}, {"role": "ai", "content": ai[:MAX_STORED_CHARS]}]
    row.messages = [*(row.messages or []), *turn][-MAX_MESSAGES:]
    row.updated_at = datetime.now(UTC)
    if created:
        await _prune(db, tenant_id, owner)
    await db.commit()


TITLE_CHARS = 60
LIST_LIMIT = 30  # the recent-chats list shows this many, newest first


def conversation_title(stored: list[dict[str, Any]] | None) -> str:
    """What the recent-chats list calls a conversation: the start of the first thing the person asked."""
    for m in stored or []:
        if m.get("role") == "human" and str(m.get("content", "")).strip():
            first_line = str(m["content"]).strip().splitlines()[0].strip()
            return first_line if len(first_line) <= TITLE_CHARS else first_line[: TITLE_CHARS - 1].rstrip() + "…"
    return "Conversation"


async def list_conversations(db: AsyncSession, tenant_id: uuid.UUID, owner: str, limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
    """This owner's recent conversations, newest first: id, title, when it was last used and how many messages it holds. Nobody else's are ever returned."""
    await set_rls_context(db, tenant_id)
    rows = (
        (
            await db.execute(
                select(CopilotConversation)
                .where(CopilotConversation.tenant_id == tenant_id, CopilotConversation.owner_key == owner)
                .order_by(CopilotConversation.updated_at.desc(), CopilotConversation.conversation_id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": r.conversation_id, "title": conversation_title(r.messages), "updatedAt": r.updated_at, "messageCount": len(r.messages or [])}
        for r in rows
    ]


async def get_conversation(db: AsyncSession, tenant_id: uuid.UUID, owner: str, conversation_id: str) -> dict[str, Any] | None:
    """One of this owner's conversations as the chat page shows it, or None (an id that belongs to someone else is simply unknown). Only each exchange's text is stored, not
    when each message was sent, so every message carries the time the conversation was last used."""
    await set_rls_context(db, tenant_id)
    row = await db.get(CopilotConversation, (tenant_id, owner, conversation_id), populate_existing=True)
    if row is None:
        return None
    return {
        "id": row.conversation_id,
        "title": conversation_title(row.messages),
        "messages": [
            {
                "id": f"{row.conversation_id}-{i}",
                "role": "user" if m.get("role") == "human" else "assistant",
                "content": m.get("content", ""),
                "createdAt": row.updated_at,
            }
            for i, m in enumerate(row.messages or [])
        ],
    }


async def delete_conversation(db: AsyncSession, tenant_id: uuid.UUID, owner: str, conversation_id: str) -> bool:
    """Delete one of this owner's conversations. False when there is none (an id that belongs to someone else is simply unknown, so nobody can delete another person's chat). The caller commits."""
    await set_rls_context(db, tenant_id)
    result = await db.execute(
        delete(CopilotConversation).where(
            CopilotConversation.tenant_id == tenant_id,
            CopilotConversation.owner_key == owner,
            CopilotConversation.conversation_id == conversation_id,
        )
    )
    return (result.rowcount or 0) > 0


async def _prune(db: AsyncSession, tenant_id: uuid.UUID, owner: str) -> None:
    """Keep this owner's newest MAX_CONVERSATIONS_PER_OWNER conversations."""
    stale = (
        select(CopilotConversation.conversation_id)
        .where(CopilotConversation.tenant_id == tenant_id, CopilotConversation.owner_key == owner)
        .order_by(CopilotConversation.updated_at.desc(), CopilotConversation.conversation_id)
        .offset(MAX_CONVERSATIONS_PER_OWNER)
    )
    ids = [r for (r,) in (await db.execute(stale)).all()]
    if ids:
        await db.execute(
            delete(CopilotConversation).where(
                CopilotConversation.tenant_id == tenant_id,
                CopilotConversation.owner_key == owner,
                CopilotConversation.conversation_id.in_(ids),
            )
        )
