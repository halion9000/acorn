"""The BIMI check: record, certificate validity, DMARC readiness, and refusing to fetch anything that is not a plain public https address."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from app.services import bimi, safe_fetch
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def cert_pem(days_left=200, started=-30, logotype=True, org="Acme Dental LLC"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org), x509.NameAttribute(NameOID.COMMON_NAME, "acme.com")])
    b = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
    b = b.not_valid_before(NOW + timedelta(days=started)).not_valid_after(NOW + timedelta(days=days_left))
    if logotype:
        b = b.add_extension(x509.UnrecognizedExtension(ObjectIdentifier("1.3.6.1.5.5.7.1.12"), b"\x30\x00"), critical=False)
    return b.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


class Dns:
    def __init__(self, bimi_txt=(), dmarc_txt=("v=DMARC1; p=reject; rua=mailto:a@x.com",)):
        self.by = {"default._bimi.acme.com": list(bimi_txt), "_dmarc.acme.com": list(dmarc_txt)}

    async def txt(self, name):
        return self.by.get(name, [])


RECORD = "v=BIMI1; l=https://acme.com/logo.svg; a=https://acme.com/vmc.pem"


def run_check(dns, pem=None, fetch_error=None):
    async def fetch(url):
        if fetch_error:
            raise fetch_error
        return pem

    return asyncio.run(bimi.check("acme.com", dns, fetch, NOW))


def test_no_record_means_not_published_and_dmarc_readiness_is_still_reported():
    out = run_check(Dns(dmarc_txt=("v=DMARC1; p=none",)))
    assert out.published is False and out.dmarc_ready is False and "quarantine or reject" in out.problems[0]
    assert run_check(Dns()).dmarc_ready is True and run_check(Dns()).problems == []


@pytest.mark.parametrize(
    "dmarc,ready",
    [("v=DMARC1; p=reject", True), ("v=DMARC1; p=quarantine; pct=100", True), ("v=DMARC1; p=quarantine; pct=50", False), ("v=DMARC1; p=none", False), ("v=spf1 -all", False)],
)
def test_bimi_needs_dmarc_at_quarantine_or_reject_on_all_mail(dmarc, ready):
    assert bimi.dmarc_enforces([dmarc])[0] is ready


def test_a_valid_verified_mark_certificate_with_time_left_has_no_problems():
    out = run_check(Dns([RECORD]), cert_pem())
    assert out.published and out.problems == []
    assert out.certificate.valid and out.certificate.is_vmc and out.certificate.days_left == 200 and out.certificate.organization == "Acme Dental LLC"
    assert out.logo_url == "https://acme.com/logo.svg" and out.certificate_url == "https://acme.com/vmc.pem"


def test_a_certificate_about_to_lapse_or_already_lapsed_is_called_out_before_the_logo_vanishes():
    soon = run_check(Dns([RECORD]), cert_pem(days_left=12))
    assert soon.certificate.valid and any("expires in 12 days" in p for p in soon.problems)
    gone = run_check(Dns([RECORD]), cert_pem(days_left=-3, started=-400))
    assert gone.certificate.valid is False and any("not valid now" in p for p in gone.problems)
    boundary = run_check(Dns([RECORD]), cert_pem(days_left=31))
    assert boundary.problems == []  # more than 30 days: not yet worth a warning


def test_an_ordinary_certificate_is_not_a_verified_mark_certificate():
    out = run_check(Dns([RECORD]), cert_pem(logotype=False))
    assert any("not a Verified Mark Certificate" in p for p in out.problems)


def test_a_record_without_a_logo_or_certificate_says_what_is_missing():
    assert any("no https logo" in p for p in run_check(Dns(["v=BIMI1; l=http://acme.com/l.svg; a=https://acme.com/vmc.pem"]), cert_pem()).problems)
    out = run_check(Dns(["v=BIMI1; l=https://acme.com/l.svg;"]))
    assert out.certificate is None and any("names no certificate" in p for p in out.problems)


def test_a_certificate_that_cannot_be_fetched_or_read_is_a_problem_not_a_crash():
    refused = run_check(Dns([RECORD]), fetch_error=bimi.FetchRefused("The certificate address did not answer."))
    assert refused.certificate is None and refused.problems == ["The certificate address did not answer."]
    garbage = run_check(Dns([RECORD]), pem=b"not a certificate")
    assert garbage.certificate is None and any("not a readable certificate" in p for p in garbage.problems)


@pytest.mark.parametrize("url", ["http://acme.com/vmc.pem", "ftp://acme.com/x", "https://user:pw@acme.com/x", "https:///x", "https://127.0.0.1/vmc.pem", "https://10.0.0.5/vmc.pem", "https://[::1]/x", "https://169.254.169.254/latest/meta-data"])
def test_only_a_plain_public_https_address_is_ever_fetched(url, monkeypatch):
    sent = []

    class Boom:  # any request that gets this far would be a request to an address we must not touch
        def __init__(self, *a, **k):
            sent.append("client")

    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", Boom)
    with pytest.raises(bimi.FetchRefused):
        asyncio.run(bimi.public_https_fetch(url))
    assert sent == []
