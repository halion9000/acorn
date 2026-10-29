"""Evidence collection records only what the platform's own data can speak to, as pending items (a person still accepts them)."""

from __future__ import annotations

from app.api.v1.endpoints import compliance as c

FACTS = {
    "users": {"active_by_role": {"analyst": 3, "tenant_admin": 1}, "active_total": 4, "deactivated": 2},
    "monitoring": {"connectors_total": 5, "connectors_enabled": 4, "connectors_healthy": 3, "alerts_last_30_days": 120},
    "response": {"alerts_last_30_days": 120, "alerts_handled": 100},
}


def test_every_automatable_control_is_a_real_control_of_its_framework():
    for fw, control in c._USER_CONTROLS | c._MONITORING_CONTROLS | c._RESPONSE_CONTROLS:
        assert control in c.FRAMEWORKS[fw], (fw, control)


def test_soc2_gets_account_and_monitoring_evidence_with_the_real_numbers():
    items = {control: (summary, payload) for control, summary, payload in c.system_evidence_for("SOC2", FACTS)}
    assert set(items) == {"CC6.1", "CC6.2", "CC6.3", "CC7.2", "CC7.3", "CC7.4"}
    assert "4 active user(s)" in items["CC6.1"][0] and "2 deactivated" in items["CC6.1"][0]
    assert "4 of 5 connector(s) enabled, 3 healthy" in items["CC7.2"][0]
    assert items["CC7.2"][1]["source"] == "platform"


def test_controls_that_need_a_document_or_attestation_are_never_invented():
    controls = {control for control, _, _ in c.system_evidence_for("SOC2", FACTS)}
    assert "CC1.1" not in controls and "CC8.1" not in controls and "A1.1" not in controls
    assert c.system_evidence_for("HIPAA", FACTS) and not any(
        ctrl == "164.308(a)(5)" for ctrl, _, _ in c.system_evidence_for("HIPAA", FACTS)
    )


def test_an_unknown_framework_yields_nothing():
    assert c.system_evidence_for("MADE-UP", FACTS) == []


def test_dora_is_gone_and_every_other_framework_lists_all_of_its_controls():
    assert "DORA" not in c.FRAMEWORKS and c.system_evidence_for("DORA", FACTS) == []
    sizes = {fw: len(controls) for fw, controls in c.FRAMEWORKS.items()}
    assert sizes == {"SOC2": 61, "ISO27001": 93, "NIST-CSF": 106, "PCI-DSS": 75, "HIPAA": 63, "CIS-IG1": 56}
    assert "A.8.15" in c.FRAMEWORKS["ISO27001"] and "GV.OC-01" in c.FRAMEWORKS["NIST-CSF"] and "Req-10.2" in c.FRAMEWORKS["PCI-DSS"]
    assert "164.312(a)(2)(i)" in c.FRAMEWORKS["HIPAA"] and "CC9.2" in c.FRAMEWORKS["SOC2"]
    assert "9.2" in c.FRAMEWORKS["CIS-IG1"] and "5.1" in c.FRAMEWORKS["CIS-IG1"]


def test_every_control_has_a_group_and_a_title_and_the_platform_evidences_only_a_small_part_of_each_framework():
    for fw, controls in c.FRAMEWORKS.items():
        assert set(c.FRAMEWORK_GROUPS[fw]) == set(controls), fw
        assert all(t.strip() for t in controls.values()) and all(g.strip() for g in c.FRAMEWORK_GROUPS[fw].values()), fw
        evidenced = {control for control, _, _ in c.system_evidence_for(fw, FACTS)}
        assert 0 < len(evidenced) <= len(controls) // 4, fw  # the rest needs a policy, attestation or runbook from a person


def test_the_pci_requirements_keep_their_old_ids_and_gain_their_sub_requirements():
    pci = c.FRAMEWORKS["PCI-DSS"]
    assert all(f"Req-{n}" in pci for n in range(1, 13))
    assert pci["Req-8.4"].startswith("Multi-factor") and pci["Req-12.10"].startswith("Suspected and confirmed")
