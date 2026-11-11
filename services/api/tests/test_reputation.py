"""The reputation facts: registration age and expiry from an RDAP record, and how the domain's own mail behaves."""

import json
from datetime import UTC, datetime

import pytest
from app.services import reputation as rp

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def rdap(**events):
    return json.dumps({"events": [{"eventAction": k, "eventDate": v} for k, v in events.items()]}).encode()


def test_registration_and_expiry_dates_are_read_from_an_rdap_record():
    r = rp.parse_rdap(
        rdap(registration="2019-03-02T10:00:00Z", expiration="2027-03-02T10:00:00Z", **{"last changed": "2026-01-01T00:00:00Z"})
    )
    assert r.registered == datetime(2019, 3, 2, 10, tzinfo=UTC) and r.expires == datetime(2027, 3, 2, 10, tzinfo=UTC)
    assert rp.parse_rdap(rdap(registration="2019-03-02T10:00:00")).registered.tzinfo is not None  # a date with no zone is read as UTC
    assert rp.parse_rdap(rdap(registration="not a date")) == rp.Registration(None, None)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"no": "events"}', b'{"events": "x"}'])
def test_anything_that_is_not_an_rdap_record_is_refused(body):
    with pytest.raises(ValueError):
        rp.parse_rdap(body)


@pytest.mark.parametrize(
    "registered,tone",
    [("2026-10-25T00:00:00Z", "bad"), ("2026-07-01T00:00:00Z", "warn"), ("2020-01-01T00:00:00Z", "good")],
)
def test_a_new_domain_is_flagged_and_an_old_one_is_not(registered, tone):
    out = rp.facts(rp.Registration(rp.parse_rdap(rdap(registration=registered)).registered, None), None, "reject", 99.0, 1000, 10, NOW)
    assert out[0].label == "Registered" and out[0].tone == tone
    assert ("common sign of abuse" in out[0].text) is (tone == "bad")


def test_a_registration_about_to_end_or_already_ended_is_called_out():
    soon = rp.facts(rp.Registration(NOW.replace(year=2020), datetime(2026, 11, 20, tzinfo=UTC)), None, "none", None, 0, 0, NOW)
    assert any(f.label == "Registration ends" and f.tone == "warn" and "17 days" in f.text for f in soon)
    gone = rp.facts(rp.Registration(NOW.replace(year=2020), datetime(2026, 10, 1, tzinfo=UTC)), None, "none", None, 0, 0, NOW)
    assert any(f.label == "Registration ends" and f.tone == "bad" for f in gone)
    far = rp.facts(rp.Registration(NOW.replace(year=2020), datetime(2028, 1, 1, tzinfo=UTC)), None, "none", None, 0, 0, NOW)
    assert any(f.label == "Registration ends" and f.tone == "good" for f in far)


def test_a_registration_that_cannot_be_read_is_said_to_be_unknown_with_the_reason_never_guessed():
    out = rp.facts(None, "The address did not answer.", "reject", 99.0, 1000, 10, NOW)
    assert out[0] == rp.Fact("Registered", "The address did not answer.", "unknown")
    assert all(f.label != "Registration ends" for f in out)


@pytest.mark.parametrize("rate,tone", [(99.0, "good"), (98.0, "good"), (95.0, "warn"), (89.9, "bad")])
def test_its_own_mail_is_judged_by_the_pass_rate_and_no_mail_is_unknown(rate, tone):
    own = [f for f in rp.facts(None, None, "none", rate, 1000, 50, NOW) if f.label == "Its own mail"][0]
    assert own.tone == tone and "1,000 messages" in own.text
    assert [f for f in rp.facts(None, None, "none", None, 0, 0, NOW) if f.label == "Its own mail"][0].tone == "unknown"


def test_the_policy_is_a_warning_only_while_it_merely_monitors():
    tones = {
        p: [f for f in rp.facts(None, None, p, 99.0, 1000, 1, NOW) if f.label == "DMARC policy"][0].tone
        for p in ("none", "quarantine", "reject", "weird")
    }
    assert tones == {"none": "warn", "quarantine": "good", "reject": "good", "weird": "unknown"}
