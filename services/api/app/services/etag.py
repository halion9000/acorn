"""ETag and If-None-Match for the heavy fleet boards: a board that has not changed since the browser last asked is answered 304 with no body, so a refresh costs almost nothing to send and nothing to redraw.

The tag is a hash of the answer itself with the fields that change on every call (``generated_at``) left out, so two answers with the same content have the same tag. It is a weak tag (``W/"..."``): the
same content, not necessarily the same bytes. Pure.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

VOLATILE = ("generated_at",)


def payload_etag(payload: Any) -> str:
    """A weak ETag for an answer (a plain dict, as ``model_dump(mode="json")`` gives), ignoring the fields that change on every call."""
    body = {k: v for k, v in payload.items() if k not in VOLATILE} if isinstance(payload, dict) else payload
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return f'W/"{hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]}"'  # noqa: S324 - not a security use


def not_modified(if_none_match: str | None, etag: str) -> bool:
    """Whether the browser already holds this version: its If-None-Match names this tag (weak comparison, so W/ is ignored) or is the wildcard."""
    if not if_none_match:
        return False
    wanted = etag.removeprefix("W/")
    for part in if_none_match.split(","):
        tag = part.strip()
        if tag == "*" or tag.removeprefix("W/") == wanted:
            return True
    return False
