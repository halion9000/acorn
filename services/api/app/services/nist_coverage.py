"""NIST CSF 2.0: which controls a client's live checks give evidence for, and how they stand today.

The mapping below is deliberately coarse and written out in full so a person can read and argue with it: each NIST CSF 2.0 control (the ones A.C.O.R.N already holds) lists the plain checks the tools report for a
client that bear on it. A control with NO mapped check present for the client says "no automated evidence" (a person has to show it); it is never called met by default. A control with mapped checks is met only when
EVERY one is met, not met when any is, partly otherwise; and "met since" is the date the last of them turned met, so the page never claims longer than all the evidence supports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

FRAMEWORK = "nist_csf"

# control id -> the check keys that bear on it
MAPPING: dict[str, tuple[str, ...]] = {
    "GV.PO-01": ("threatmate_frameworks",),
    "GV.RM-01": ("threatmate_cyber_insurance", "halopsa_agreement"),
    "ID.AM-01": ("ninjaone_unsupported_os", "threatmate_end_of_life", "threatmate_firmware", "meraki_licence"),
    "ID.RA-01": (
        "ninjaone_patching",
        "threatmate_patching",
        "threatmate_external_exposure",
        "threatmate_hardening",
        "threatmate_security_score",
        "threatmate_m365_controls",
        "ninjaone_reboot",
    ),
    "PR.AA-01": (
        "password_expiry",
        "banned_passwords",
        "onprem_password_protection",
        "password_hash_sync",
        "sspr_enabled",
        "emergency_access_accounts",
        "cloud_only_admins",
        "ga_count",
        "admin_license_footprint",
        "liongard_stale_licensed_users",
        "threatmate_google_stale_accounts",
        "threatmate_cloud_identity",
    ),
    "PR.AA-03": (
        "legacy_auth_ca",
        "device_code_ca",
        "weak_auth_methods",
        "system_preferred_mfa",
        "register_security_info_ca",
        "authenticator_fatigue",
        "liongard_m365_admin_mfa_policy",
        "dnsfilter_org_mfa",
        "meraki_admin_2fa",
        "user_risk_ca",
        "signin_risk_ca",
        "managed_device_ca",
        "threatmate_google_admins",
    ),
    "PR.AA-05": (
        "ga_local_admin",
        "local_admin_join",
        "laps",
        "user_consent",
        "admin_consent_workflow",
        "create_tenants",
        "create_security_groups",
        "guest_access",
        "guest_dynamic_group",
        "sharepoint_external_sharing",
        "calendar_external_sharing",
        "autoelevate_enforcing",
    ),
    "PR.DS-01": ("dlp_enabled", "dlp_teams", "sensitivity_label_policies"),
    "PR.DS-02": ("sharepoint_modern_auth", "threatmate_dmarc", "liongard_email_domain_records", "liongard_iis_certificates"),
    "PR.PS-04": ("unified_audit_log", "mailbox_audit_actions", "audit_bypass"),
    "DE.CM-01": (
        "dnsfilter_traffic",
        "dnsfilter_threat_blocking",
        "meraki_wan",
        "meraki_dual_wan",
        "anti_phishing",
        "safe_links",
        "safe_attachments",
        "safe_attachments_collab",
        "zap_teams",
        "outbound_spam_notify",
        "malware_admin_notify",
        "mail_forwarding_blocked",
        "liongard_m365_external_forwarding",
        "external_sender_tag",
    ),
    "DE.CM-03": (
        "admin_signin_frequency",
        "idle_session_timeout",
        "liongard_ad_bad_logins",
        "threatmate_google_failed_logins",
        "shared_mailbox_signin",
    ),
    "DE.AE-02": (
        "huntress_protection",
        "huntress_quiet_agents",
        "huntress_old_agents",
        "huntress_extra_coverage",
        "ninjaone_antivirus",
        "ninjaone_huntress_service",
        "liongard_edr_coverage",
        "fieldeffect_account_risk",
        "fieldeffect_device_risk",
        "autoelevate_requests",
        "threatmate_deep_dark_web",
        "threatmate_ai_tools",
    ),
    "RC.RP-01": ("saas_backup_email", "datto_saas_seats", "slide_appliance", "slide_verification", "slide_alerts", "liongard_datto_bcdr"),
}

STATUS_ORDER = {"not_met": 0, "partly": 1, "met": 2}


def flatten_checks(tool_checks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{check key: {status, evidence, since}} from the posture's ``tool_checks`` (source -> {checks: [...]}). If two sources report the same key the worse status wins (pure)."""
    out: dict[str, dict[str, Any]] = {}
    for source in (tool_checks or {}).values():
        checks = source.get("checks", []) if isinstance(source, dict) else getattr(source, "checks", [])
        for c in checks:
            get = c.get if isinstance(c, dict) else (lambda k, d=None, c=c: getattr(c, k, d))
            key, status = get("key"), get("status")
            if not isinstance(key, str) or status not in STATUS_ORDER:
                continue
            row = {"status": status, "evidence": str(get("evidence", "") or "")[:300], "since": get("since")}
            if key not in out or STATUS_ORDER[status] < STATUS_ORDER[out[key]["status"]]:
                out[key] = row
    return out


def mfa_check(identity: dict[str, Any] | None) -> dict[str, Any] | None:
    """A synthetic check from the second-factor coverage A.C.O.R.N holds: met at 95% or more of people covered, partly at 80%, else not met (pure)."""
    if not identity or not identity.get("people"):
        return None
    people = int(identity["people"])
    covered = int(identity.get("with_mfa") or 0) + int(identity.get("not_required") or 0)
    share = covered / people
    status = "met" if share >= 0.95 else "partly" if share >= 0.80 else "not_met"
    return {"status": status, "evidence": f"{covered} of {people} people have a second sign-in step ({round(share * 100)}%)", "since": None}


def control_status(checks: dict[str, dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    """How one control stands, from the mapped checks present for this client (pure)."""
    present = [(k, checks[k]) for k in keys if k in checks]
    if not present:
        return {"status": "no_evidence", "checks": [], "met_since": None}
    statuses = {c["status"] for _, c in present}
    status = "met" if statuses == {"met"} else "not_met" if "not_met" in statuses else "partly"
    since = None
    if status == "met":
        dates = [c["since"] for _, c in present if isinstance(c.get("since"), datetime)]
        since = max(dates) if len(dates) == len(present) and dates else None
    return {
        "status": status,
        "checks": [
            {"key": k, "status": c["status"], "evidence": c["evidence"]}
            for k, c in sorted(present, key=lambda kc: (STATUS_ORDER[kc[1]["status"]], kc[0]))
        ],
        "met_since": since,
    }


def coverage(controls: list[dict[str, str]], tool_checks: dict[str, Any], identity: dict[str, Any] | None) -> dict[str, Any]:
    """Every NIST control A.C.O.R.N holds, with its standing for one client, plus the totals (pure). ``controls``: [{control_id, category, title}]."""
    checks = flatten_checks(tool_checks)
    mfa = mfa_check(identity)
    if mfa is not None:
        checks["mfa_coverage"] = mfa
    mapping = {k: v + (("mfa_coverage",) if k == "PR.AA-03" else ()) for k, v in MAPPING.items()}
    rows = []
    for c in controls:
        s = control_status(checks, mapping.get(c["control_id"], ()))
        rows.append({"control_id": c["control_id"], "category": c["category"], "title": c["title"], **s})
    totals = {k: sum(1 for r in rows if r["status"] == k) for k in ("met", "partly", "not_met", "no_evidence")}
    return {"framework": FRAMEWORK, "controls": rows, "totals": totals}
