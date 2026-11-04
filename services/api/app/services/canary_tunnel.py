"""The Cloudflare tunnel token for the public honeytoken address, handed over by CORE.

CORE has a "Cloudflare canary" card where the owner pastes the tunnel token once. CORE sends it here; this module checks it, and keeps it in the update hand-off folder (the same folder the Update
button writes to, ``ACORN_UPDATE_CTL_DIR``) as ``cloudflared.token``. The update script on the VM, which already owns ``.env``, reads that file into ``.env`` and starts the tunnel. The API container
never starts anything and never returns the token to anyone: ``state`` says only whether one is stored and when it last changed.

A Cloudflare tunnel token is base64 text that decodes to a small JSON object with the account tag ``a``, the tunnel id ``t`` and the secret ``s``. Anything else is refused, which also means nothing that
could break out of a line in ``.env`` (spaces, quotes, newlines) is ever written.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TOKEN_FILE = "cloudflared.token"
MAX_TOKEN_CHARS = 2000
_B64 = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")


class TokenRefused(ValueError):
    """The text is not a Cloudflare tunnel token (the message says why, never echoing the text)."""


def check_token(raw: str) -> str:
    """The token trimmed of surrounding whitespace, or ``TokenRefused``."""
    token = (raw or "").strip()
    if not token:
        raise TokenRefused("The token is empty.")
    if len(token) > MAX_TOKEN_CHARS:
        raise TokenRefused("The token is too long to be a Cloudflare tunnel token.")
    if not _B64.match(token):
        raise TokenRefused("The token has characters a Cloudflare tunnel token never has.")
    padded = token + "=" * (-len(token) % 4)
    try:
        data = json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True))
    except (binascii.Error, ValueError):
        raise TokenRefused("The token is not a Cloudflare tunnel token (it does not decode).") from None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data.get(k) for k in ("a", "t", "s")):
        raise TokenRefused("The token is not a Cloudflare tunnel token (it lacks the account, tunnel or secret).")
    return token


@dataclass(frozen=True)
class TunnelState:
    stored: bool
    changed_at: datetime | None = None
    tunnel_id: str | None = None  # not secret: it is shown in Cloudflare's own page; lets the owner see WHICH tunnel is stored


def _tunnel_id(token: str) -> str | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        return str(json.loads(base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True))["t"])
    except Exception:  # noqa: BLE001 - only a label for the screen
        return None


def store_token(directory: Path | None, token: str) -> bool:
    """Write the (already checked) token. Returns True when it differs from what was stored. Raises ``RuntimeError`` when there is no hand-off folder."""
    if directory is None or not directory.is_dir():
        raise RuntimeError("There is no update hand-off folder on this server, so the token cannot be kept.")
    target = directory / TOKEN_FILE
    try:
        if target.read_text(encoding="utf-8").strip() == token:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cloudflared-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)  # one step: the update script never sees half a token
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def state(directory: Path | None) -> TunnelState:
    if directory is None:
        return TunnelState(stored=False)
    target = directory / TOKEN_FILE
    try:
        token = target.read_text(encoding="utf-8").strip()
        changed = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
    except OSError:
        return TunnelState(stored=False)
    return TunnelState(stored=bool(token), changed_at=changed, tunnel_id=_tunnel_id(token))
