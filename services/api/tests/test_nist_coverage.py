"""NIST CSF coverage from live checks: never met by default, met only when every mapped check is met, and 'met since' is the latest of them."""

from datetime import UTC, datetime

from app.services import nist_coverage as nc

D1, D2 = datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
CONTROLS = [
    {"control_id": "PR.AA-03", "category": "Protect", "title": "Users and devices are authenticated"},
    {"control_id": "DE.AE-02", "category": "Detect", "title": "Events analysed"},
    {"control_id": "RC.RP-01", "category": "Recover", "title": "Recovery plan"},
    {"control_id": "GV.OC-01", "category": "Govern", "title": "Mission"},
]


def tc(*checks):
    return {"src": {"checks": [dict(key=k, status=s, evidence=f"ev {k}", since=d) for k, s, d in checks]}}


def test_a_control_with_no_mapped_check_present_is_no_evidence_never_met():
    out = nc.coverage(CONTROLS, tc(("ninjaone_antivirus", "met", D1)), None)
    rows = {r["control_id"]: r for r in out["controls"]}
    assert rows["GV.OC-01"]["status"] == "no_evidence"
    assert rows["RC.RP-01"]["status"] == "no_evidence"
    assert out["totals"] == {"met": 1, "partly": 0, "not_met": 0, "no_evidence": 3}


def test_met_only_when_every_mapped_check_is_met_not_met_when_any_is_and_met_since_is_the_latest_date():
    met = nc.coverage(CONTROLS, tc(("huntress_protection", "met", D1), ("ninjaone_antivirus", "met", D2)), None)
    row = {r["control_id"]: r for r in met["controls"]}["DE.AE-02"]
    assert row["status"] == "met" and row["met_since"] == D2
    partly = nc.coverage(CONTROLS, tc(("huntress_protection", "met", D1), ("ninjaone_antivirus", "partly", D2)), None)
    assert {r["control_id"]: r for r in partly["controls"]}["DE.AE-02"]["status"] == "partly"
    bad = nc.coverage(CONTROLS, tc(("huntress_protection", "met", D1), ("ninjaone_antivirus", "not_met", D2), ("liongard_edr_coverage", "partly", None)), None)
    row = {r["control_id"]: r for r in bad["controls"]}["DE.AE-02"]
    assert row["status"] == "not_met" and row["met_since"] is None
    assert [c["key"] for c in row["checks"]][0] == "ninjaone_antivirus", "the worst check is listed first"


def test_met_since_is_unknown_when_any_met_check_has_no_date():
    out = nc.coverage(CONTROLS, tc(("huntress_protection", "met", D1), ("ninjaone_antivirus", "met", None)), None)
    assert {r["control_id"]: r for r in out["controls"]}["DE.AE-02"]["met_since"] is None


def test_second_factor_coverage_counts_as_evidence_for_authentication_at_95_and_80_percent():
    def status(with_mfa, not_required=0, people=100):
        out = nc.coverage(CONTROLS, {}, {"people": people, "with_mfa": with_mfa, "not_required": not_required})
        return {r["control_id"]: r for r in out["controls"]}["PR.AA-03"]["status"]

    assert status(95) == "met" and status(80) == "partly" and status(79) == "not_met"
    assert status(90, not_required=5) == "met"
    out = nc.coverage(CONTROLS, {}, None)
    assert {r["control_id"]: r for r in out["controls"]}["PR.AA-03"]["status"] == "no_evidence", "no identity data: not guessed"


def test_the_same_check_from_two_sources_keeps_the_worse_status_and_junk_is_ignored():
    both = {"a": {"checks": [dict(key="ninjaone_antivirus", status="met", evidence="x", since=D1)]}, "b": {"checks": [dict(key="ninjaone_antivirus", status="not_met", evidence="y", since=D1), dict(key=5, status="met"), dict(key="z", status="weird")]}}
    flat = nc.flatten_checks(both)
    assert flat["ninjaone_antivirus"]["status"] == "not_met" and set(flat) == {"ninjaone_antivirus"}


def test_every_mapped_control_is_a_real_seeded_nist_control_and_lists_at_least_one_check():
    import re
    from pathlib import Path

    sql = (Path(__file__).resolve().parent.parent / "migrations" / "006_compliance_frameworks.sql").read_text(encoding="utf-8")
    seeded = set(re.findall(r"\('nist_csf', '([A-Z]{2}\.[A-Z]{2}-\d{2})'", sql))
    assert set(nc.MAPPING) <= seeded, sorted(set(nc.MAPPING) - seeded)
    assert all(keys for keys in nc.MAPPING.values())
