"""Automated control tests: what the connected tools already say about a client, turned into evidence for the controls it speaks to.

A.C.O.R.N holds a client's checks (CIPP and the other tools each report checks such as "admins have multi-factor", "antivirus is running", "backups are verified": a key, met, partly or not met, and what was found).
A test here names the checks that bear on one security practice and the controls of each framework that practice answers. Evaluating a test looks at the checks of the tools the client really has:

* every check the test names that the client has is met  -> the test PASSES   (accepted evidence for its controls)
* any such check is not met                               -> the test FAILS    (rejected evidence)
* some are only partly met and none failed                -> the test is PARTLY met (pending evidence: it is not counted as healthy)
* the client has none of the checks                       -> NOT TESTED (no evidence is written: a tool the client does not use proves nothing either way)

Recording writes one evidence record per control a test answers, marked ``raw_payload.source = "checks"``; only those records are replaced next time, so a person's own evidence, and Secureframe's, are never touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text

SOURCE = "checks"


@dataclass(frozen=True)
class ControlTest:
    id: str
    title: str
    checks: tuple[str, ...]
    controls: tuple[tuple[str, str], ...]  # (framework, control id)
    why: str = field(default="", compare=False)


TESTS: tuple[ControlTest, ...] = (
    ControlTest(
        "mfa",
        "Multi-factor sign-in is required",
        (
            "liongard_m365_admin_mfa_policy",
            "liongard_m365_users_mfa_policy",
            "liongard_m365_weak_mfa",
            "meraki_admin_2fa",
            "dnsfilter_org_mfa",
        ),
        (("SOC2", "CC6.1"), ("NIST-CSF", "PR.AA-03"), ("CIS-IG1", "6.5"), ("ISO27001", "A.8.5"), ("HIPAA", "164.312(d)")),
        "People prove who they are with more than a password.",
    ),
    ControlTest(
        "legacy-auth",
        "Legacy sign-in that skips multi-factor is blocked",
        ("cipp_ca_legacy_auth", "liongard_m365_legacy_auth"),
        (("SOC2", "CC6.1"), ("NIST-CSF", "PR.AA-03"), ("ISO27001", "A.8.5")),
        "Old protocols cannot be used to get around multi-factor.",
    ),
    ControlTest(
        "access-removal",
        "Accounts that are no longer used are found and removed",
        ("cipp_inactive_accounts", "liongard_stale_licensed_users", "threatmate_google_stale_accounts"),
        (("SOC2", "CC6.3"), ("NIST-CSF", "PR.AA-05"), ("ISO27001", "A.5.15"), ("HIPAA", "164.312(a)(1)")),
        "Access is taken away when it is no longer needed.",
    ),
    ControlTest(
        "malware",
        "Machines are protected against malware",
        ("huntress_protection", "huntress_quiet_agents", "ninjaone_antivirus", "ninjaone_huntress_service", "liongard_edr_coverage"),
        (("SOC2", "CC6.8"), ("NIST-CSF", "DE.CM-09"), ("CIS-IG1", "10.1"), ("ISO27001", "A.8.7"), ("HIPAA", "164.308(a)(5)(ii)(B)")),
        "Endpoint protection is installed and reporting.",
    ),
    ControlTest(
        "patching",
        "Operating systems and software are patched and supported",
        (
            "ninjaone_patching",
            "ninjaone_server_patching",
            "ninjaone_software_patches",
            "ninjaone_unsupported_os",
            "addigy_unsupported_macos",
            "threatmate_patching",
            "threatmate_end_of_life",
        ),
        (("SOC2", "CC7.1"), ("NIST-CSF", "PR.PS-02"), ("CIS-IG1", "7.4"), ("ISO27001", "A.8.8")),
        "Known flaws are fixed on a schedule and nothing runs past its support.",
    ),
    ControlTest(
        "vulnerabilities",
        "Vulnerabilities are found and the dangerous ones dealt with",
        ("cipp_defender_vulnerabilities", "threatmate_external_exposure"),
        (("SOC2", "CC7.1"), ("NIST-CSF", "ID.RA-01"), ("CIS-IG1", "7.1"), ("ISO27001", "A.8.8")),
        "Weaknesses are identified, and the exploitable ones are not left open.",
    ),
    ControlTest(
        "backups",
        "Data is backed up and the backups are checked",
        (
            "saas_backup_microsoft",
            "saas_backup_google",
            "saas_backup_email",
            "liongard_datto_bcdr",
            "slide_appliance",
            "slide_verification",
            "slide_alerts",
        ),
        (("SOC2", "A1.2"), ("NIST-CSF", "PR.DS-11"), ("CIS-IG1", "11.2"), ("ISO27001", "A.8.13")),
        "Backups exist for the data and the machines, and a recovery has been proven.",
    ),
    ControlTest(
        "disk-encryption",
        "Disks are encrypted",
        ("liongard_disk_encryption",),
        (("NIST-CSF", "PR.DS-01"), ("HIPAA", "164.312(a)(2)(iv)")),
        "Data at rest is unreadable if a machine is lost.",
    ),
    ControlTest(
        "dns-filtering",
        "DNS filtering protects the network",
        ("dnsfilter_agents_silent", "dnsfilter_threat_blocking", "dnsfilter_traffic"),
        (("SOC2", "CC6.6"), ("CIS-IG1", "9.2")),
        "Known bad destinations are blocked at the DNS lookup.",
    ),
    ControlTest(
        "awareness",
        "People are trained and tested on phishing",
        ("sat_training_assigned", "sat_training_completion", "sat_phishing_simulation"),
        (("CIS-IG1", "14.1"),),
        "A security awareness programme is running and people complete it.",
    ),
    ControlTest(
        "email-authentication",
        "Email domains are protected against spoofing",
        ("threatmate_dmarc", "liongard_email_domain_records"),
        (("SOC2", "CC6.7"), ("NIST-CSF", "PR.DS-02"), ("ISO27001", "A.5.14"), ("HIPAA", "164.312(e)(1)")),
        "SPF, DKIM and DMARC are published so nobody can send as the organization.",
    ),
    ControlTest(
        "certificates",
        "Certificates and domains do not lapse",
        ("itglue_domain_expiry", "itglue_certificate_expiry", "liongard_iis_certificates"),
        (("SOC2", "CC6.7"), ("NIST-CSF", "PR.DS-02"), ("ISO27001", "A.8.24"), ("HIPAA", "164.312(e)(1)")),
        "Encrypted connections keep working because certificates and domains are renewed in time.",
    ),
    ControlTest(
        "network-security",
        "Network equipment is supported and not left open",
        ("meraki_open_wifi", "meraki_end_of_support", "liongard_addigy_firewall"),
        (("SOC2", "CC6.6"), ("NIST-CSF", "PR.IR-01"), ("CIS-IG1", "12.1"), ("ISO27001", "A.8.20")),
        "Firewalls and switches get vendor updates, and wireless networks are not open to anyone.",
    ),
    ControlTest(
        "asset-health",
        "Machines and network devices are monitored and healthy",
        ("ninjaone_disk_health", "ninjaone_disk_space", "ninjaone_reboot", "meraki_devices_offline", "threatmate_agents_online"),
        (("SOC2", "A1.1"), ("NIST-CSF", "DE.CM-01"), ("ISO27001", "A.8.16")),
        "Capacity and health are watched so a failing disk or an offline device is noticed.",
    ),
)
BY_ID = {t.id: t for t in TESTS}

PASS, FAIL, PARTLY, NOT_TESTED = "pass", "fail", "partly", "not_tested"
EVIDENCE_STATUS = {PASS: "accepted", FAIL: "rejected", PARTLY: "pending"}


def evaluate(test: ControlTest, checks: dict[str, str]) -> dict[str, Any]:
    """The result of one test from the client's checks ``{key: met | partly | not_met}`` (pure)."""
    seen = {k: checks[k] for k in test.checks if k in checks}
    if not seen:
        return {"state": NOT_TESTED, "seen": {}, "met": 0, "total": 0}
    statuses = list(seen.values())
    state = FAIL if "not_met" in statuses else PASS if all(s == "met" for s in statuses) else PARTLY
    return {"state": state, "seen": seen, "met": statuses.count("met"), "total": len(statuses)}


def evaluate_all(checks: dict[str, str]) -> list[dict[str, Any]]:
    """Every test with its result, failing first, then partly, then passing, then those with nothing to go on (pure)."""
    order = {FAIL: 0, PARTLY: 1, PASS: 2, NOT_TESTED: 3}
    out = [{"test": t, **evaluate(t, checks)} for t in TESTS]
    return sorted(out, key=lambda r: (order[r["state"]], r["test"].title))


def evidence_rows(results: list[dict[str, Any]], enabled: set[str]) -> list[dict[str, Any]]:
    """The evidence records to write: one per control a tested test answers, only for frameworks that are on (pure)."""
    rows: list[dict[str, Any]] = []
    for r in results:
        test: ControlTest = r["test"]
        status = EVIDENCE_STATUS.get(r["state"])
        if status is None:
            continue
        verdict = {PASS: "passes", FAIL: "fails", PARTLY: "is only partly met"}[r["state"]]
        for framework, control in test.controls:
            if framework not in enabled:
                continue
            rows.append(
                {
                    "framework": framework,
                    "control_id": control,
                    "status": status,
                    "summary": f"Automated test: {test.title} {verdict} ({r['met']} of {r['total']} checks met).",
                    "payload": {"source": SOURCE, "test": test.id, "state": r["state"], "checks": r["seen"]},
                }
            )
    return rows


async def record(db: Any, tenant_id: Any, rows: list[dict[str, Any]], now: datetime) -> dict[str, int]:
    """Replace the records this module wrote for the tenant with ``rows``; everything else is left alone."""
    removed = (
        await db.execute(
            text("DELETE FROM aisoc_compliance_evidence WHERE tenant_id = :t AND raw_payload ->> 'source' = :s"),
            {"t": tenant_id, "s": SOURCE},
        )
    ).rowcount or 0
    for r in rows:
        await db.execute(
            text(
                """
                INSERT INTO aisoc_compliance_evidence
                    (tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, reviewed_by, reviewed_at, status)
                VALUES (:t, :f, :c, 'other', :summary, CAST(:payload AS JSONB), :now, 'Automated test', :now, :status)
                """
            ),
            {
                "t": tenant_id,
                "f": r["framework"],
                "c": r["control_id"],
                "summary": r["summary"],
                "payload": json.dumps(r["payload"]),
                "now": now,
                "status": r["status"],
            },
        )
    return {"written": len(rows), "replaced": int(removed)}
