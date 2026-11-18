"""One security topic, the controls of every framework that ask for it (pure).

Each topic names the controls (identifiers from ``compliance_catalog``) that cover it in each framework, so one piece of work or evidence can be seen to count toward several frameworks, and a framework's controls
can be compared with another's. The mapping is a working crosswalk for planning, not a statement an auditor has signed off: a control in two frameworks on the same topic may still ask for different detail.
"""

from __future__ import annotations

# topic id -> (title, {framework: [control ids]})
TOPICS: dict[str, tuple[str, dict[str, list[str]]]] = {
    "policy": ("Written security policy", {"SOC2": ["CC5.3"], "ISO27001": ["A.5.1", "A.5.37"], "NIST-CSF": ["GV.PO-01", "GV.PO-02"], "PCI-DSS": ["Req-12.1"], "HIPAA": ["164.316(a)", "164.316(b)(1)"]}),
    "responsibility": ("Named security responsibility", {"SOC2": ["CC1.3", "CC1.5"], "ISO27001": ["A.5.2"], "HIPAA": ["164.308(a)(2)"], "PCI-DSS": ["Req-12.4"], "CIS-IG1": ["17.1"]}),
    "risk-assessment": ("Risk assessment and treatment", {"SOC2": ["CC3.2", "CC9.1"], "NIST-CSF": ["GV.RM-01", "ID.RA-05", "ID.RA-06"], "PCI-DSS": ["Req-12.3"], "HIPAA": ["164.308(a)(1)(ii)(A)", "164.308(a)(1)(ii)(B)"]}),
    "asset-inventory": ("Inventory of devices and software", {"ISO27001": ["A.5.9"], "NIST-CSF": ["ID.AM-01", "ID.AM-02"], "CIS-IG1": ["1.1", "2.1"], "PCI-DSS": ["Req-12.5"], "HIPAA": ["164.310(d)(2)(iii)"]}),
    "access-granting": ("Granting and changing access", {"SOC2": ["CC6.2", "CC6.3"], "ISO27001": ["A.5.15", "A.5.16", "A.5.18"], "NIST-CSF": ["PR.AA-01", "PR.AA-05"], "PCI-DSS": ["Req-7.2", "Req-8.2"], "HIPAA": ["164.308(a)(4)(ii)(B)", "164.308(a)(4)(ii)(C)"], "CIS-IG1": ["6.1"]}),
    "access-removal": ("Removing access when people leave", {"SOC2": ["CC6.3"], "ISO27001": ["A.6.5"], "PCI-DSS": ["Req-8.2"], "HIPAA": ["164.308(a)(3)(ii)(C)"], "CIS-IG1": ["6.2", "5.3"]}),
    "least-privilege": ("Least privilege and administrator accounts", {"SOC2": ["CC6.3"], "ISO27001": ["A.8.2"], "PCI-DSS": ["Req-7.2", "Req-7.3"], "HIPAA": ["164.312(a)(1)"], "CIS-IG1": ["5.4"]}),
    "authentication": ("Strong authentication and multi-factor", {"SOC2": ["CC6.1"], "ISO27001": ["A.5.17", "A.8.5"], "NIST-CSF": ["PR.AA-03"], "PCI-DSS": ["Req-8.3", "Req-8.4"], "HIPAA": ["164.312(d)", "164.308(a)(5)(ii)(D)"], "CIS-IG1": ["5.2", "6.3", "6.4", "6.5"]}),
    "unique-ids": ("Unique user identification", {"ISO27001": ["A.5.16"], "PCI-DSS": ["Req-8.2"], "HIPAA": ["164.312(a)(2)(i)"], "NIST-CSF": ["PR.AA-01"], "CIS-IG1": ["5.1"]}),
    "encryption": ("Encryption of data at rest and in transit", {"SOC2": ["CC6.7"], "ISO27001": ["A.8.24"], "PCI-DSS": ["Req-3.5", "Req-3.6"], "HIPAA": ["164.312(a)(2)(iv)", "164.312(e)(1)", "164.312(e)(2)(ii)"], "NIST-CSF": ["PR.DS-01", "PR.DS-02"], "CIS-IG1": ["3.6"]}),
    "logging": ("Audit logs collected and kept", {"SOC2": ["CC7.2"], "ISO27001": ["A.8.15"], "NIST-CSF": ["PR.PS-04"], "PCI-DSS": ["Req-10.2", "Req-10.5"], "HIPAA": ["164.312(b)"], "CIS-IG1": ["8.1", "8.2", "8.3"]}),
    "monitoring": ("Monitoring for suspicious activity", {"SOC2": ["CC7.2", "CC7.3"], "ISO27001": ["A.8.16"], "NIST-CSF": ["DE.CM-01", "DE.CM-03", "DE.CM-09", "DE.AE-02"], "PCI-DSS": ["Req-10.4", "Req-11.5"], "HIPAA": ["164.308(a)(1)(ii)(D)", "164.308(a)(5)(ii)(C)"]}),
    "malware": ("Protection against malware", {"SOC2": ["CC6.8"], "ISO27001": ["A.8.7"], "NIST-CSF": ["PR.PS-05"], "PCI-DSS": ["Req-5.2", "Req-5.3"], "HIPAA": ["164.308(a)(5)(ii)(B)"], "CIS-IG1": ["10.1", "10.2"]}),
    "vulnerabilities": ("Finding and fixing vulnerabilities", {"SOC2": ["CC7.1"], "ISO27001": ["A.8.8"], "NIST-CSF": ["ID.RA-01"], "PCI-DSS": ["Req-6.3", "Req-11.3"], "CIS-IG1": ["7.1", "7.2"]}),
    "patching": ("Patching operating systems and applications", {"ISO27001": ["A.8.8"], "NIST-CSF": ["PR.PS-02"], "PCI-DSS": ["Req-6.3"], "CIS-IG1": ["7.3", "7.4", "2.2"]}),
    "secure-configuration": ("Secure configuration of systems", {"SOC2": ["CC7.1"], "ISO27001": ["A.8.9"], "NIST-CSF": ["PR.PS-01"], "PCI-DSS": ["Req-2.2"], "CIS-IG1": ["4.1", "4.2", "4.7"]}),
    "network-protection": ("Firewalls and network boundaries", {"SOC2": ["CC6.6"], "ISO27001": ["A.8.20", "A.8.22"], "NIST-CSF": ["PR.IR-01"], "PCI-DSS": ["Req-1.2", "Req-1.3", "Req-1.4"], "CIS-IG1": ["4.4", "4.5"]}),
    "backup": ("Backups and recovery", {"SOC2": ["A1.2"], "ISO27001": ["A.8.13"], "NIST-CSF": ["PR.DS-11", "RC.RP-03"], "HIPAA": ["164.308(a)(7)(ii)(A)", "164.310(d)(2)(iv)"], "CIS-IG1": ["11.1", "11.2", "11.3"]}),
    "recovery-testing": ("Testing disaster recovery", {"SOC2": ["A1.3"], "ISO27001": ["A.5.30"], "HIPAA": ["164.308(a)(7)(ii)(B)", "164.308(a)(7)(ii)(D)"], "NIST-CSF": ["RC.RP-01"]}),
    "incident-response": ("Incident response plan and handling", {"SOC2": ["CC7.3", "CC7.4", "CC7.5"], "ISO27001": ["A.5.24", "A.5.26"], "NIST-CSF": ["RS.MA-01", "RS.MA-02", "RS.MI-01"], "PCI-DSS": ["Req-12.10"], "HIPAA": ["164.308(a)(6)", "164.308(a)(6)(ii)"], "CIS-IG1": ["17.1", "17.3"]}),
    "awareness-training": ("Security awareness training", {"SOC2": ["CC1.4"], "ISO27001": ["A.6.3"], "NIST-CSF": ["PR.AT-01"], "PCI-DSS": ["Req-12.6"], "HIPAA": ["164.308(a)(5)"], "CIS-IG1": ["14.1", "14.2"]}),
    "vendor-management": ("Vendor and supplier risk", {"SOC2": ["CC9.2"], "ISO27001": ["A.5.19", "A.5.20", "A.5.22"], "NIST-CSF": ["GV.SC-04", "GV.SC-07"], "PCI-DSS": ["Req-12.8", "Req-12.9"], "HIPAA": ["164.308(b)(1)", "164.314(a)(1)"], "CIS-IG1": ["15.1"]}),
    "change-management": ("Managing changes to systems", {"SOC2": ["CC8.1"], "ISO27001": ["A.8.32"], "NIST-CSF": ["ID.RA-07"], "PCI-DSS": ["Req-6.5"]}),
    "data-disposal": ("Secure disposal of data and equipment", {"SOC2": ["CC6.5", "C1.2"], "ISO27001": ["A.7.14", "A.8.10"], "PCI-DSS": ["Req-3.2"], "HIPAA": ["164.310(d)(2)(i)", "164.310(d)(2)(ii)"], "CIS-IG1": ["3.5"]}),
    "physical-access": ("Physical access to facilities", {"SOC2": ["CC6.4"], "ISO27001": ["A.7.1", "A.7.2"], "NIST-CSF": ["PR.AA-06"], "PCI-DSS": ["Req-9.2", "Req-9.3"], "HIPAA": ["164.310(a)(1)", "164.310(a)(2)(iii)"]}),
    "session-lock": ("Automatic session locking", {"ISO27001": ["A.7.7"], "HIPAA": ["164.312(a)(2)(iii)"], "CIS-IG1": ["4.3"]}),
}

FRAMEWORK_NAMES = {"SOC2": "SOC 2", "ISO27001": "ISO 27001", "NIST-CSF": "NIST CSF", "PCI-DSS": "PCI DSS", "HIPAA": "HIPAA", "CIS-IG1": "CIS IG1"}


def topics_for(framework: str, control_id: str) -> list[str]:
    """The topics a control belongs to (pure)."""
    return [t for t, (_title, by_fw) in TOPICS.items() if control_id in by_fw.get(framework, [])]


def related(framework: str, control_id: str) -> dict[str, list[str]]:
    """For a control: every other framework and the controls on the same topics, so evidence for it can be reused (pure)."""
    out: dict[str, list[str]] = {}
    for t in topics_for(framework, control_id):
        for fw, ids in TOPICS[t][1].items():
            if fw == framework:
                continue
            for i in ids:
                if i not in out.setdefault(fw, []):
                    out[fw].append(i)
    return {fw: ids for fw, ids in out.items() if ids}
