"""Reading the one shared DMARC mailbox through Microsoft Graph, and feeding what it holds into the parser and the store.

The mailbox is read, never changed: the app only needs the Mail.Read application permission, limited to that one mailbox by an Exchange application access policy (so it cannot read anyone
else's mail). Nothing is moved or marked read; "already seen" is a cursor (the newest message received so far) kept in dmarc_ingest_state, and a report that is read twice is stored once.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

from app.services.alert_email.graph import GraphMailer, MailError, _graph_error
from app.services.dmarc_report import MAX_COMPRESSED, DmarcReportError, parse_report

REPORT_SUFFIXES = (".xml", ".gz", ".zip", ".xml.gz")
PAGE = 50
MAX_PAGES = 10


@dataclass
class Message:
    id: str
    received: datetime
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


class MailboxReader(Protocol):
    async def new_messages(self, since: datetime | None) -> list[Message]: ...


def looks_like_report(name: str) -> bool:
    return name.lower().endswith(REPORT_SUFFIXES)


class GraphMailboxReader(GraphMailer):
    """GraphMailer's token handling, used to READ one mailbox (``sender`` is the mailbox address)."""

    async def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        token = await self._token()
        response = await self._request("GET", url, params=params, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 401:  # an expired token: one fresh attempt
            token = await self._token(force=True)
            response = await self._request("GET", url, params=params, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            transient = response.status_code in (429, 500, 502, 503, 504)
            raise MailError(f"Microsoft refused the mailbox read: {_graph_error(response, self._secrets)}", permanent=not transient)
        try:
            return response.json()
        except ValueError:
            raise MailError("Microsoft's mailbox answer was not understood", permanent=False) from None

    async def new_messages(self, since: datetime | None) -> list[Message]:
        mailbox = quote(self.sender, safe="@")
        flt = "hasAttachments eq true" + (f" and receivedDateTime gt {since.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}" if since else "")
        url: str | None = f"{self.base_url}/users/{mailbox}/mailFolders/inbox/messages"
        params: dict[str, str] | None = {"$filter": flt, "$orderby": "receivedDateTime asc", "$top": str(PAGE), "$select": "id,receivedDateTime"}
        out: list[Message] = []
        for _ in range(MAX_PAGES):
            if url is None:
                break
            page = await self._get(url, params)
            for item in page.get("value", []):
                received = datetime.fromisoformat(str(item["receivedDateTime"]).replace("Z", "+00:00"))
                out.append(Message(id=str(item["id"]), received=received, attachments=await self._attachments(mailbox, str(item["id"]))))
            url, params = page.get("@odata.nextLink"), None
        return out

    async def _attachments(self, mailbox: str, message_id: str) -> list[tuple[str, bytes]]:
        data = await self._get(
            f"{self.base_url}/users/{mailbox}/messages/{quote(message_id, safe='')}/attachments", {"$select": "name,contentType,contentBytes,size"}
        )
        out: list[tuple[str, bytes]] = []
        for att in data.get("value", []):
            name = str(att.get("name") or "")
            if att.get("@odata.type", "#microsoft.graph.fileAttachment") != "#microsoft.graph.fileAttachment" or not looks_like_report(name):
                continue
            if int(att.get("size") or 0) > MAX_COMPRESSED:
                continue  # too big to be a report: the parser would refuse it anyway
            try:
                out.append((name, base64.b64decode(att.get("contentBytes") or "", validate=False)))
            except (binascii.Error, ValueError):
                continue
        return out


@dataclass
class IngestResult:
    stored: int = 0
    duplicates: int = 0
    rejected: int = 0
    messages: int = 0
    error: str | None = None


async def ingest_once(
    session_factory: Callable[[], Any],
    reader: MailboxReader,
    owner_id: uuid.UUID,
    *,
    store: Callable[..., Awaitable[Any]],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> IngestResult:
    """One pass: read what arrived since the cursor, store each report, and move the cursor to the newest message that was handled. A failure from the mailbox keeps the cursor where it was."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.db.rls_sessions import mark_platform  # noqa: PLC0415
    from app.models.dmarc import DmarcIngestState  # noqa: PLC0415

    result = IngestResult()
    async with session_factory() as db:
        mark_platform(db)
        state = (await db.execute(select(DmarcIngestState).where(DmarcIngestState.tenant_id == owner_id))).scalar_one_or_none()
        if state is None:
            state = DmarcIngestState(tenant_id=owner_id, stored=0, rejected=0)
            db.add(state)
        since = state.cursor.replace(tzinfo=UTC) if state.cursor is not None and state.cursor.tzinfo is None else state.cursor
        try:
            messages = await reader.new_messages(since)
        except MailError as exc:
            result.error = str(exc)
            state.last_run_at, state.last_error = now(), result.error
            await db.commit()
            return result
        newest = since
        for message in messages:
            result.messages += 1
            for name, blob in message.attachments:
                try:
                    report = parse_report(blob)
                except DmarcReportError:
                    result.rejected += 1
                    continue
                stored = await store(db, owner_id, report)
                if stored.outcome == "stored":
                    result.stored += 1
                else:
                    result.duplicates += 1
            if newest is None or message.received > newest:
                newest = message.received
        state.cursor, state.last_run_at, state.last_error = newest, now(), None
        state.stored += result.stored
        state.rejected += result.rejected
        await db.commit()
    return result
