"""A client's documentation (IT Glue documents, configurations, runbooks), searched in plain words.

CORE sends the text; this stores it per client (row-level security) and finds it again for Leafy and the console. The search is Postgres full text: any of the words in a question can match, best match first,
and a question that names a client looks only in that client's documents. Nothing here writes to IT Glue, and password entries are never sent.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, column, delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.client_document import ClientDocument

MAX_BODY = 30_000
STALE_DAYS = 14
# A ticket does not change once it is closed, so CORE does not send it again every week; it is kept by the date the ticketing tool last touched it instead of by when it was last received.
TICKET_KIND = "ticket"
TICKET_KEEP_DAYS = 730
# A ticket's answer is spread across its notes, so a ticket's result carries the start of the whole thread rather than the two best fragments a document gets.
TICKET_SNIPPET_CHARS = 1500
MAX_TERMS = 12
SNIPPET_OPTIONS = 'MaxFragments=2, MaxWords=40, MinWords=15, StartSel="", StopSel="", FragmentDelimiter=" ... "'

_TERM = re.compile(r"[a-z0-9]+")
_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "co", "corp", "corporation", "company", "pllc", "lp", "llp", "pc"}


def clean_text(text: str | None, limit: int = MAX_BODY) -> str:
    """The text with control characters (a NUL stops Postgres) and runs of blank lines removed, cut at ``limit``."""
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


_SECRET_LINE = re.compile(
    r"(?im)(\b(?:pass(?:word|wd|phrase|code)?|pwd|secret|api[ _-]?key|token|private[ _-]?key|recovery[ _-]?key|otp|2fa)\b\s*(?:is|are)?\s*[:=]\s*)(\S.*)$"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)


# A secret written into a sentence: "the wifi key is Summer2025!", "changed the password to Welcome1". The word after is blanked when it looks like a secret (a digit or symbol in it, or mixed capitals) and is not an
# ordinary word ("password is required").
_NATURAL = re.compile(
    r"(\b(?:password|passcode|passphrase|passwd|pwd|pw|pin|psk|token|secret|key)\s+(?:is|was|to|=)\s+)([^\s,;]+)", re.IGNORECASE
)
_NOT_SECRET = frozenset(
    "required,expire,expires,expired,expiry,expiration,changed,reset,correct,incorrect,wrong,invalid,enabled,disabled,blank,empty,stored,saved,shared,unknown,unchanged,managed,needed,protected,policy,complexity,locked,unlocked,working,fine,good,default,none,same,different,unique,strong,weak,longer,shorter,sufficient,hidden".split(
        ","
    )
)


def _looks_like_secret(word: str) -> bool:
    w = re.sub(r"[.!?)\"']+$", "", word)
    if not w or w.lower() in _NOT_SECRET:
        return False
    return bool(re.search(r"[0-9!@#$%^&*_+=-]", w)) or (bool(re.search(r"[a-z]", w)) and bool(re.search(r"[A-Z]", w)) and len(w) >= 6)


def redact_secrets(text: str) -> str:
    """The text with what looks like a secret blanked: a private key block, and whatever follows "password:", "token =", "api key:" and the like on a line. Documentation pasted from a person's notes can hold one; the
    password entries themselves are never sent (only their name and link), and this is the second layer behind CORE's own."""
    text = _PRIVATE_KEY.sub("[private key redacted]", text)
    text = _SECRET_LINE.sub(lambda m: m.group(1) + "[redacted]", text)
    return _NATURAL.sub(lambda m: m.group(1) + "[redacted]" if _looks_like_secret(m.group(2)) else m.group(0), text)


def search_terms(message: str) -> list[str]:
    """The words of a question worth looking up: letters and digits only (so none can break the query), two or more characters, once each, at most 12."""
    seen: list[str] = []
    for term in _TERM.findall((message or "").lower()):
        if len(term) >= 2 and term not in seen:
            seen.append(term)
    return seen[:MAX_TERMS]


def tsquery_text(terms: list[str]) -> str | None:
    """``a | b | c``: a document matches on any word, and the ranking puts the ones with most of them first. None when there is nothing to look up."""
    clean = [t for t in terms if _TERM.fullmatch(t)]
    return " | ".join(clean) if clean else None


def _name_key(name: str) -> str:
    """A client's name as words, without a leading "The" and without legal suffixes (Inc, LLC and the like); words inside the name stay, since the question has them too."""
    words = _TERM.findall(name.lower())
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def clients_named(message: str, clients: list[tuple[uuid.UUID, str]]) -> list[uuid.UUID]:
    """The clients whose whole name (without Inc, LLC and the like) appears in the question, in order of appearance. A question that names none gets an empty list."""
    haystack = " " + " ".join(_TERM.findall((message or "").lower())) + " "
    found: list[tuple[int, uuid.UUID]] = []
    for cid, name in clients:
        key = _name_key(name)
        if len(key) < 3:
            continue
        at = haystack.find(f" {key} ")
        if at >= 0:
            found.append((at, cid))
    return [cid for _, cid in sorted(found)]


@dataclass
class Hit:
    tenant_id: uuid.UUID
    kind: str
    title: str
    folder: str | None
    url: str | None
    snippet: str
    rank: float


async def search_documents(db: Any, tenant_ids: list[uuid.UUID], query: str, limit: int = 8) -> list[Hit]:
    """The best matches for a question among these clients' documents. The caller supplies a session that may read all of ``tenant_ids``."""
    tsq = tsquery_text(search_terms(query))
    if tsq is None or not tenant_ids:
        return []
    q = func.to_tsquery("english", tsq)
    search = column("search")
    rows = (
        await db.execute(
            select(
                ClientDocument.tenant_id,
                ClientDocument.kind,
                ClientDocument.title,
                ClientDocument.folder,
                ClientDocument.url,
                case(
                    (ClientDocument.kind == TICKET_KIND, func.left(ClientDocument.body, TICKET_SNIPPET_CHARS)),
                    else_=func.ts_headline("english", ClientDocument.body, q, SNIPPET_OPTIONS),
                ).label("snippet"),
                func.ts_rank(search, q).label("rank"),
            )
            .where(ClientDocument.tenant_id.in_(tenant_ids), search.op("@@")(q))
            .order_by(desc("rank"), ClientDocument.title)
            .limit(max(1, min(limit, 30)))
        )
    ).all()
    return [
        Hit(
            r.tenant_id,
            r.kind,
            r.title,
            r.folder,
            r.url,
            clean_text(r.snippet, TICKET_SNIPPET_CHARS if r.kind == TICKET_KIND else 600) or clean_text(r.title, 300),
            float(r.rank or 0.0),
        )
        for r in rows
    ]


async def apply_documents(db: Any, by_tenant: dict[uuid.UUID, list[Any]], vendor: str, now: datetime | None = None) -> int:
    """Store each record under its client (inside that client's own row-level-security scope) and drop the records of this vendor not refreshed for two weeks.

    The caller has already worked out which client each record belongs to; ``acting_as_tenant`` is applied here, one client at a time.
    """
    from app.db.rls_scope import acting_as_tenant

    now = now or datetime.now(UTC)
    accepted = 0
    for tid, items in by_tenant.items():
        async with acting_as_tenant(db, tid):
            values: list[dict[str, Any]] = []
            seen: set[str] = set()
            for it in items:
                if it.id in seen:
                    continue
                seen.add(it.id)
                values.append(
                    {
                        "tenant_id": tid,
                        "vendor": vendor,
                        "external_id": it.id,
                        "kind": it.kind,
                        "title": clean_text(it.title, 300) or it.id,
                        "folder": clean_text(it.folder, 300) or None,
                        "body": redact_secrets(clean_text(it.body)),
                        "url": it.url,
                        "vendor_updated_at": it.updated_at,
                        "received_at": now,
                    }
                )
            if values:
                stmt = pg_insert(ClientDocument).values(values)
                update = {c: stmt.excluded[c] for c in values[0] if c not in ("tenant_id", "vendor", "external_id")}
                await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "vendor", "external_id"], set_=update))
                accepted += len(values)
            await db.execute(
                delete(ClientDocument).where(
                    ClientDocument.tenant_id == tid,
                    ClientDocument.vendor == vendor,
                    ClientDocument.kind != TICKET_KIND,
                    ClientDocument.received_at < now - timedelta(days=STALE_DAYS),
                )
            )
            await db.execute(
                delete(ClientDocument).where(
                    ClientDocument.tenant_id == tid,
                    ClientDocument.vendor == vendor,
                    ClientDocument.kind == TICKET_KIND,
                    ClientDocument.vendor_updated_at < now - timedelta(days=TICKET_KEEP_DAYS),
                )
            )
    return accepted


async def summary(db: Any, tenant_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, str, int, datetime | None]]:
    """For each client with any: the kind of record, how many, and when the latest was refreshed."""
    rows = (
        await db.execute(
            select(ClientDocument.tenant_id, ClientDocument.kind, func.count(), func.max(ClientDocument.received_at))
            .where(ClientDocument.tenant_id.in_(tenant_ids))
            .group_by(ClientDocument.tenant_id, ClientDocument.kind)
        )
    ).all()
    return [(r[0], r[1], int(r[2]), r[3]) for r in rows]
