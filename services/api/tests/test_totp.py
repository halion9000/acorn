"""Authenticator-app codes: checked against the RFC 6238 published test values, never accepted twice, recovery codes spent once."""

import base64

from app.services import totp

# RFC 6238 appendix B: the SHA-1 secret is the ASCII string "12345678901234567890"; at T = 59 s the 8-digit code is 94287082, so the 6-digit one is its last six digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


def test_codes_match_the_published_rfc_6238_values():
    assert totp.code_for_step(RFC_SECRET, 59 // 30) == "287082"
    assert totp.code_for_step(RFC_SECRET, 1111111109 // 30) == "081804"
    assert totp.code_for_step(RFC_SECRET, 1234567890 // 30) == "005924"
    assert totp.code_for_step(RFC_SECRET, 20000000000 // 30) == "353130"


def test_a_code_is_accepted_for_its_step_and_one_step_either_side_but_not_further():
    step = 1_000_000
    now = step * 30 + 5
    code = totp.code_for_step(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now) == step
    assert totp.verify(RFC_SECRET, code, now + 30) == step, "a clock a step slow"
    assert totp.verify(RFC_SECRET, code, now - 30) == step, "a clock a step fast"
    assert totp.verify(RFC_SECRET, code, now + 90) is None, "three steps away is too old"


def test_a_code_cannot_be_used_twice_or_after_a_later_one():
    step = 2_000_000
    now = step * 30
    code = totp.code_for_step(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now, last_used_step=step) is None, "the same step again is a replay"
    assert totp.verify(RFC_SECRET, code, now, last_used_step=step + 1) is None
    assert totp.verify(RFC_SECRET, code, now, last_used_step=step - 1) == step


def test_anything_that_is_not_six_digits_is_refused():
    for bad in ("", "12345", "1234567", "abcdef", "12 34 5x", None):
        assert totp.verify(RFC_SECRET, bad, 1_000_000 * 30) is None  # type: ignore[arg-type]
    code = totp.code_for_step(RFC_SECRET, 1_000_000)
    assert totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", 1_000_000 * 30) == 1_000_000, "spaces as an app shows them are fine"


def test_a_new_secret_is_160_bits_of_base32_and_the_uri_carries_what_an_app_needs():
    s = totp.new_secret()
    assert len(base64.b32decode(s + "=" * (-len(s) % 8))) == 20 and s != totp.new_secret()
    uri = totp.otpauth_uri(s, "hal@example.com")
    assert (
        uri.startswith("otpauth://totp/A.C.O.R.N%3Ahal%40example.com?")
        and f"secret={s}" in uri
        and "issuer=A.C.O.R.N" in uri
        and "digits=6" in uri
        and "period=30" in uri
    )


def test_recovery_codes_are_ten_distinct_values_stored_only_as_hashes_and_each_works_once():
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    hashes = [totp.hash_recovery(c) for c in codes]
    assert not any(c.replace("-", "") in h for c in codes for h in hashes)
    left = totp.use_recovery(hashes, codes[3].upper())
    assert left is not None and len(left) == 9 and totp.hash_recovery(codes[3]) not in left
    assert totp.use_recovery(left, codes[3]) is None, "a spent code does not work again"
    assert totp.use_recovery(hashes, "00000-00000") is None and totp.use_recovery(hashes, "short") is None
