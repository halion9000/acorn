"""Let CORE send its feed token in a header instead of in the web address.

The CORE feed routes (``/api/v1/inbox/core-feed/{tenant_token}/...``) take their secret in the path, which puts it in every proxy and access log. CORE can now ask for
``/api/v1/inbox/core-feed/_/...`` and send the secret as ``X-Core-Feed-Token``; this middleware swaps the header's value into the path for the router, on a COPY of the request (the original, which is
what the servers log, keeps the ``_``). The old form with the secret in the path still works, so CORE and A.C.O.R.N can be updated in either order. A missing or malformed header leaves the ``_`` in place,
which the route refuses like any wrong token.
"""

from __future__ import annotations

import re
from typing import Any

PREFIX = "/api/v1/inbox/core-feed/_/"
HEADER = b"x-core-feed-token"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,200}$")


def rewritten_path(path: str, header_value: str | None) -> str | None:
    """The path with the header's token in place of ``_``, or None when this request is not of that form (pure)."""
    if not path.startswith(PREFIX) or not header_value or not _TOKEN.fullmatch(header_value.strip()):
        return None
    return "/api/v1/inbox/core-feed/" + header_value.strip() + "/" + path[len(PREFIX) :]


class CoreFeedTokenMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and str(scope.get("path", "")).startswith(PREFIX):
            value = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == HEADER), None)
            new_path = rewritten_path(scope["path"], value)
            if new_path is not None:
                scope = {**scope, "path": new_path, "raw_path": new_path.encode("latin-1")}
        await self.app(scope, receive, send)
