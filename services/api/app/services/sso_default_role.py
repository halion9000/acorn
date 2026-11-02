"""The role a person gets the first time they sign in with Microsoft and have no account yet.

An administrator chooses it in Settings > Roles & Permissions; it is kept in the workspace's own settings. Until one is chosen, the server setting MS_SSO_NEW_USER_ROLE applies (Viewer when that is not set).
A choice is a built-in role or one of the workspace's custom roles (held on top of Viewer, the same way Add member does it). Administrator roles are never given automatically, whatever is stored.
"""

from __future__ import annotations

import uuid
from typing import Any

KEY = "sso_new_user_role"
# Built-in roles that may be the automatic role. Administrator is deliberately not here, and neither are the platform and legacy admin roles.
ALLOWED_BUILTIN: tuple[str, ...] = ("viewer", "soc_analyst", "threat_hunter", "soc_lead")


def effective(workspace_settings: dict[str, Any] | None, server_role: str) -> tuple[str, uuid.UUID | None, str]:
    """(built-in role, custom role id or None, where it came from: "setting" or "server"). A stored value that is not usable falls back to the server setting."""
    raw = (workspace_settings or {}).get(KEY)
    if isinstance(raw, dict) and raw.get("role") in ALLOWED_BUILTIN:
        custom: uuid.UUID | None = None
        if raw.get("custom_role_id"):
            try:
                custom = uuid.UUID(str(raw["custom_role_id"]))
            except ValueError:
                return server_role, None, "server"
        return str(raw["role"]), custom, "setting"
    return server_role, None, "server"


def stored(role: str, custom_role_id: uuid.UUID | None) -> dict[str, Any]:
    return {"role": role, "custom_role_id": str(custom_role_id) if custom_role_id else None}
