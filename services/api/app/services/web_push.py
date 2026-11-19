"""Web push for a critical alert (roadmap r7-af-39): the VAPID key, the signed header and the encrypted message, written on the ``cryptography`` package already in use (RFC 8030, 8291 and 8292).

Pure apart from ``send``: every function takes what it needs and returns bytes or text, so the encryption can be checked by decrypting it again (the tests do, as a browser would).
The message is the standard ``aes128gcm`` content coding: a salt, the record size, our one-time public key, then the encrypted payload. The push service never sees the text.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
MAX_PAYLOAD = RECORD_SIZE - 17  # one record: the payload, a delimiter byte and the 16-byte tag


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid() -> tuple[str, str]:
    """A new VAPID key pair as (private key raw, public key uncompressed), both URL-safe base64 without padding."""
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u(raw), b64u(_public_bytes(key))


def _load_private(private_b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64u_decode(private_b64), "big"), ec.SECP256R1())


def vapid_header(endpoint: str, private_b64: str, public_b64: str, subject: str, now: float | None = None) -> str:
    """The Authorization header for a push to ``endpoint``: a signed token naming the push service, valid twelve hours."""
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("A push endpoint must be an https address.")
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now if now is not None else time.time()) + 12 * 3600), "sub": subject}
    signing = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + b64u(json.dumps(claims, separators=(",", ":")).encode())
    r, s = decode_dss_signature(_load_private(private_b64).sign(signing.encode("ascii"), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={signing}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={public_b64}"


def encrypt_payload(payload: bytes, p256dh_b64: str, auth_b64: str, *, salt: bytes | None = None, ephemeral: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """The request body for one message to a browser, from its subscription keys (RFC 8291 with the aes128gcm coding)."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("The push message is too long.")
    ua_public = b64u_decode(p256dh_b64)
    auth_secret = b64u_decode(auth_b64)
    ours = ephemeral or ec.generate_private_key(ec.SECP256R1())
    our_public = _public_bytes(ours)
    shared = ours.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret, info=b"WebPush: info\x00" + ua_public + our_public).derive(shared)
    salt = salt or os.urandom(16)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">IB", RECORD_SIZE, len(our_public)) + our_public + sealed


def decrypt_payload(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_b64: str) -> bytes:
    """What a browser does with the body (used by the tests to prove the message can be read by its owner and nobody else)."""
    salt, key_len = body[:16], body[20]
    our_public = body[21 : 21 + key_len]
    sealed = body[21 + key_len :]
    ua_public = _public_bytes(ua_private)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), our_public))
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=b64u_decode(auth_b64), info=b"WebPush: info\x00" + ua_public + our_public).derive(shared)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, sealed, None)
    return plain[: plain.rindex(b"\x02")]


def alert_message(client: str, title: str, severity: str) -> bytes:
    """The text a critical alert pushes: a short title and body, with the page to open."""
    body = {"title": f"{severity.capitalize()} alert: {client}"[:100], "body": title[:200], "url": "/alerts"}
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def should_drop(status_code: int) -> bool:
    """Whether the push service says this subscription is gone for good (404 or 410): it is deleted, not retried."""
    return status_code in (404, 410)


async def send(client: Any, endpoint: str, p256dh: str, auth: str, payload: bytes, private_b64: str, public_b64: str, subject: str) -> int:
    """One message to one browser. Returns the push service's status code. ``client`` is an httpx.AsyncClient."""
    res = await client.post(
        endpoint,
        content=encrypt_payload(payload, p256dh, auth),
        headers={"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "3600", "Urgency": "high", "Authorization": vapid_header(endpoint, private_b64, public_b64, subject)},
        timeout=10,
    )
    return int(res.status_code)
