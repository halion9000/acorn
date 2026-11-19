"""Web push crypto: the message can be read by its owner, the VAPID token verifies (pure)."""

import json

import pytest
from app.services import web_push as wp
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


def browser():
    key = ec.generate_private_key(ec.SECP256R1())
    return key, wp.b64u(wp._public_bytes(key)), wp.b64u(b"0123456789abcdef")


def test_a_message_is_readable_by_its_owner_and_not_by_another_browser():
    key, p256dh, auth = browser()
    body = wp.encrypt_payload(b'{"title":"Critical alert"}', p256dh, auth)
    assert wp.decrypt_payload(body, key, auth) == b'{"title":"Critical alert"}'
    other, _p, _a = browser()
    with pytest.raises(Exception):  # noqa: B017 - any failure to decrypt is the point
        wp.decrypt_payload(body, other, auth)
    assert b"Critical" not in body, "the push service must not see the text"


def test_two_messages_to_one_browser_differ_and_a_long_one_is_refused():
    _k, p256dh, auth = browser()
    assert wp.encrypt_payload(b"x", p256dh, auth) != wp.encrypt_payload(b"x", p256dh, auth)
    with pytest.raises(ValueError):
        wp.encrypt_payload(b"x" * (wp.MAX_PAYLOAD + 1), p256dh, auth)


def test_the_vapid_token_names_the_push_service_expires_and_verifies_with_the_public_key():
    private, public = wp.generate_vapid()
    header = wp.vapid_header("https://push.example.net/abc/def", private, public, "mailto:ops@example.com", now=1000.0)
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == public
    head, claims, sig = token.split(".")
    assert json.loads(wp.b64u_decode(claims)) == {"aud": "https://push.example.net", "exp": 1000 + 12 * 3600, "sub": "mailto:ops@example.com"}
    raw = wp.b64u_decode(sig)
    public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), wp.b64u_decode(public))
    public_key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        public_key.verify(encode_dss_signature(1, 1), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_a_plain_http_endpoint_is_refused_and_gone_subscriptions_are_dropped():
    private, public = wp.generate_vapid()
    with pytest.raises(ValueError):
        wp.vapid_header("http://push.example.net/x", private, public, "mailto:a@b.co")
    assert wp.should_drop(404) and wp.should_drop(410) and not wp.should_drop(500) and not wp.should_drop(201)


def test_the_alert_message_has_a_title_a_body_and_the_page_to_open():
    msg = json.loads(wp.alert_message("Acme", "Ransomware behaviour on PC-1", "critical"))
    assert msg == {"title": "Critical alert: Acme", "body": "Ransomware behaviour on PC-1", "url": "/alerts"}
