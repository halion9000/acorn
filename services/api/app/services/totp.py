"""Authenticator-app codes (TOTP, RFC 6238) for the password sign-in that remains (improvement A13).

Works with Google Authenticator, Microsoft Authenticator and any other app that reads a standard ``otpauth://`` key: 6 digits, a new code every 30 seconds, SHA-1 (the only algorithm every app supports).
Plain standard library: nothing here talks to the network, and the secret is only ever stored encrypted (``app.security.credential_vault``).

 - A code is accepted for the current 30-second step and one step either side (clocks drift), and never twice: ``verify`` returns the step it matched so the caller can refuse any step it has already seen.
 - Recovery codes (ten, single use) are for a lost phone. Only their hashes are stored. They are long random values, so a plain SHA-256 is enough; they are shown once, at the moment they are made.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # steps either side of now that are still accepted
RECOVERY_CODE_COUNT = 10


def new_secret() -> str:
    """A fresh 160-bit secret as base32, the form authenticator apps take (pure apart from the random source)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    padded = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(padded + "=" * (-len(padded) % 8))


def code_for_step(secret_b32: str, step: int) -> str:
    """The code for one 30-second step (RFC 4226 dynamic truncation of an HMAC-SHA1) (pure)."""
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**DIGITS)).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret_b32: str, code: str, now: float | None = None, last_used_step: int | None = None) -> int | None:
    """The step the code belongs to when it is right and has not been used (pure): within the window around now, and later than ``last_used_step``. None otherwise.

    Compared in constant time. Anything that is not exactly six digits is refused before any work is done."""
    cleaned = (code or "").strip().replace(" ", "")
    if len(cleaned) != DIGITS or not cleaned.isdigit():
        return None
    here = current_step(now)
    for step in range(here - WINDOW, here + WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(code_for_step(secret_b32, step), cleaned):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "A.C.O.R.N") -> str:
    """The address an authenticator app reads (as text or a QR code): the account label, the secret and the issuer (pure)."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def new_recovery_codes() -> list[str]:
    """Ten single-use codes like ``a1b2c-3d4e5`` (50 random bits each), to be shown once."""
    out = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5)
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def normalize_recovery(code: str) -> str:
    return (code or "").strip().lower().replace(" ", "").replace("-", "")


def hash_recovery(code: str) -> str:
    return hashlib.sha256(normalize_recovery(code).encode()).hexdigest()


def use_recovery(hashes: list[str], code: str) -> list[str] | None:
    """The list of hashes left after spending this recovery code, or None when it is not one of them (pure). Each code works once."""
    candidate = hash_recovery(code)
    if len(normalize_recovery(code)) != 10:
        return None
    for h in hashes:
        if hmac.compare_digest(h, candidate):
            remaining = list(hashes)
            remaining.remove(h)
            return remaining
    return None
