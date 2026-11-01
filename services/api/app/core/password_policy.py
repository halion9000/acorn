"""The rule for a NEW password set through the change-password and admin-reset routes (sign-in itself never applies it, so existing passwords keep working)."""

from __future__ import annotations

MIN_LENGTH = 12
MAX_LENGTH = 128  # bcrypt-style hashes read only the first 72 bytes; a very long value is refused rather than silently cut


def password_problem(new: str, current: str | None = None) -> str | None:
    """A sentence saying why `new` is not acceptable, or None when it is."""
    if len(new) < MIN_LENGTH:
        return f"The new password must be at least {MIN_LENGTH} characters."
    if len(new) > MAX_LENGTH:
        return f"The new password must be at most {MAX_LENGTH} characters."
    if new.strip() != new:
        return "The new password cannot start or end with a space."
    if current is not None and new == current:
        return "The new password must be different from the current one."
    return None
