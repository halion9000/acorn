"""The full control list of each compliance framework the console offers, grouped the way the framework groups them.

Each framework is a list of ``(group, control_id, title)``. Titles are shortened. Identifiers are the framework's own (SOC 2 criteria, ISO/IEC 27001:2022 Annex A, NIST CSF 2.0 subcategories, PCI DSS v4.0
requirements, HIPAA Security Rule standards and implementation specifications), so an auditor can match each line to the source.

Which controls the platform can evidence from its own data is decided in ``app.api.v1.endpoints.compliance``; everything else here waits for a person's attestation, policy or runbook.
"""

from __future__ import annotations

Catalog = list[tuple[str, str, str]]

SOC2: Catalog = [
    # Common criteria (security)
    ("CC1 Control environment", "CC1.1", "Commitment to integrity and ethical values"),
    ("CC1 Control environment", "CC1.2", "Board independence and oversight of controls"),
    ("CC1 Control environment", "CC1.3", "Structures, reporting lines, authorities and responsibilities"),
    ("CC1 Control environment", "CC1.4", "Commitment to attract, develop and retain competent people"),
    ("CC1 Control environment", "CC1.5", "Accountability for internal control responsibilities"),
    ("CC2 Communication and information", "CC2.1", "Uses relevant, quality information for internal control"),
    ("CC2 Communication and information", "CC2.2", "Communicates internally, including objectives and responsibilities"),
    ("CC2 Communication and information", "CC2.3", "Communicates with external parties"),
    ("CC3 Risk assessment", "CC3.1", "Specifies objectives clearly enough to identify risks"),
    ("CC3 Risk assessment", "CC3.2", "Identifies and analyses risks to objectives"),
    ("CC3 Risk assessment", "CC3.3", "Considers the potential for fraud"),
    ("CC3 Risk assessment", "CC3.4", "Identifies and assesses changes that could affect controls"),
    ("CC4 Monitoring activities", "CC4.1", "Selects, develops and performs ongoing or separate evaluations"),
    ("CC4 Monitoring activities", "CC4.2", "Evaluates and communicates control deficiencies"),
    ("CC5 Control activities", "CC5.1", "Selects and develops control activities that mitigate risks"),
    ("CC5 Control activities", "CC5.2", "Selects and develops general controls over technology"),
    ("CC5 Control activities", "CC5.3", "Deploys control activities through policies and procedures"),
    ("CC6 Logical and physical access", "CC6.1", "Logical access security software, infrastructure and architecture"),
    ("CC6 Logical and physical access", "CC6.2", "Registration and authorization of new users"),
    ("CC6 Logical and physical access", "CC6.3", "Role-based access, least privilege, and removal of access"),
    ("CC6 Logical and physical access", "CC6.4", "Restricts physical access to facilities and protected assets"),
    ("CC6 Logical and physical access", "CC6.5", "Disposes of physical assets and data securely"),
    ("CC6 Logical and physical access", "CC6.6", "Protects against threats from outside the system boundaries"),
    ("CC6 Logical and physical access", "CC6.7", "Restricts transmission, movement and removal of information"),
    ("CC6 Logical and physical access", "CC6.8", "Prevents and detects unauthorized or malicious software"),
    ("CC7 System operations", "CC7.1", "Detects configuration changes and new vulnerabilities"),
    ("CC7 System operations", "CC7.2", "Monitors system components for anomalies and security events"),
    ("CC7 System operations", "CC7.3", "Evaluates security events to determine whether they are incidents"),
    ("CC7 System operations", "CC7.4", "Responds to identified security incidents"),
    ("CC7 System operations", "CC7.5", "Recovers from identified security incidents"),
    ("CC8 Change management", "CC8.1", "Authorizes, designs, tests, approves and implements changes"),
    ("CC9 Risk mitigation", "CC9.1", "Identifies and mitigates risks from business disruptions"),
    ("CC9 Risk mitigation", "CC9.2", "Assesses and manages risks from vendors and business partners"),
    # Availability
    ("A1 Availability", "A1.1", "Maintains, monitors and evaluates current processing capacity"),
    ("A1 Availability", "A1.2", "Environmental protections, backup and recovery infrastructure"),
    ("A1 Availability", "A1.3", "Tests recovery plan procedures"),
    # Confidentiality
    ("C1 Confidentiality", "C1.1", "Identifies and maintains confidential information"),
    ("C1 Confidentiality", "C1.2", "Disposes of confidential information"),
    # Processing integrity
    ("PI1 Processing integrity", "PI1.1", "Defines and uses information about processing objectives and specifications"),
    ("PI1 Processing integrity", "PI1.2", "Controls over system inputs"),
    ("PI1 Processing integrity", "PI1.3", "Controls over system processing"),
    ("PI1 Processing integrity", "PI1.4", "Controls over system outputs"),
    ("PI1 Processing integrity", "PI1.5", "Stores inputs, items in processing and outputs completely and accurately"),
    # Privacy
    ("P1 Privacy: notice", "P1.1", "Privacy notice to data subjects"),
    ("P2 Privacy: choice and consent", "P2.1", "Choice and consent communicated and obtained"),
    ("P3 Privacy: collection", "P3.1", "Collects personal information consistent with objectives"),
    ("P3 Privacy: collection", "P3.2", "Explicit consent for sensitive information"),
    ("P4 Privacy: use, retention, disposal", "P4.1", "Limits use of personal information"),
    ("P4 Privacy: use, retention, disposal", "P4.2", "Retains personal information as needed"),
    ("P4 Privacy: use, retention, disposal", "P4.3", "Securely disposes of personal information"),
    ("P5 Privacy: access", "P5.1", "Grants data subjects access to their information"),
    ("P5 Privacy: access", "P5.2", "Corrects, amends or appends personal information"),
    ("P6 Privacy: disclosure and notification", "P6.1", "Discloses to third parties with consent"),
    ("P6 Privacy: disclosure and notification", "P6.2", "Records authorized disclosures"),
    ("P6 Privacy: disclosure and notification", "P6.3", "Records unauthorized disclosures"),
    ("P6 Privacy: disclosure and notification", "P6.4", "Obtains privacy commitments from vendors"),
    ("P6 Privacy: disclosure and notification", "P6.5", "Obtains commitments to notify of incidents from vendors"),
    ("P6 Privacy: disclosure and notification", "P6.6", "Notifies data subjects of breaches"),
    ("P6 Privacy: disclosure and notification", "P6.7", "Provides an accounting of disclosures"),
    ("P7 Privacy: quality", "P7.1", "Maintains accurate personal information"),
    ("P8 Privacy: monitoring and enforcement", "P8.1", "Handles privacy inquiries, complaints and disputes"),
]

# ISO/IEC 27001:2022, Annex A (93 controls).
ISO27001: Catalog = [
    *[
        ("A.5 Organizational controls", f"A.5.{n}", t)
        for n, t in enumerate(
            [
                "Policies for information security",
                "Information security roles and responsibilities",
                "Segregation of duties",
                "Management responsibilities",
                "Contact with authorities",
                "Contact with special interest groups",
                "Threat intelligence",
                "Information security in project management",
                "Inventory of information and other associated assets",
                "Acceptable use of information and other associated assets",
                "Return of assets",
                "Classification of information",
                "Labelling of information",
                "Information transfer",
                "Access control",
                "Identity management",
                "Authentication information",
                "Access rights",
                "Information security in supplier relationships",
                "Addressing information security within supplier agreements",
                "Managing information security in the ICT supply chain",
                "Monitoring, review and change management of supplier services",
                "Information security for use of cloud services",
                "Information security incident management planning and preparation",
                "Assessment and decision on information security events",
                "Response to information security incidents",
                "Learning from information security incidents",
                "Collection of evidence",
                "Information security during disruption",
                "ICT readiness for business continuity",
                "Legal, statutory, regulatory and contractual requirements",
                "Intellectual property rights",
                "Protection of records",
                "Privacy and protection of PII",
                "Independent review of information security",
                "Compliance with policies, rules and standards for information security",
                "Documented operating procedures",
            ],
            start=1,
        )
    ],
    *[
        ("A.6 People controls", f"A.6.{n}", t)
        for n, t in enumerate(
            [
                "Screening",
                "Terms and conditions of employment",
                "Information security awareness, education and training",
                "Disciplinary process",
                "Responsibilities after termination or change of employment",
                "Confidentiality or non-disclosure agreements",
                "Remote working",
                "Information security event reporting",
            ],
            start=1,
        )
    ],
    *[
        ("A.7 Physical controls", f"A.7.{n}", t)
        for n, t in enumerate(
            [
                "Physical security perimeters",
                "Physical entry",
                "Securing offices, rooms and facilities",
                "Physical security monitoring",
                "Protecting against physical and environmental threats",
                "Working in secure areas",
                "Clear desk and clear screen",
                "Equipment siting and protection",
                "Security of assets off-premises",
                "Storage media",
                "Supporting utilities",
                "Cabling security",
                "Equipment maintenance",
                "Secure disposal or re-use of equipment",
            ],
            start=1,
        )
    ],
    *[
        ("A.8 Technological controls", f"A.8.{n}", t)
        for n, t in enumerate(
            [
                "User endpoint devices",
                "Privileged access rights",
                "Information access restriction",
                "Access to source code",
                "Secure authentication",
                "Capacity management",
                "Protection against malware",
                "Management of technical vulnerabilities",
                "Configuration management",
                "Information deletion",
                "Data masking",
                "Data leakage prevention",
                "Information backup",
                "Redundancy of information processing facilities",
                "Logging",
                "Monitoring activities",
                "Clock synchronization",
                "Use of privileged utility programs",
                "Installation of software on operational systems",
                "Networks security",
                "Security of network services",
                "Segregation of networks",
                "Web filtering",
                "Use of cryptography",
                "Secure development life cycle",
                "Application security requirements",
                "Secure system architecture and engineering principles",
                "Secure coding",
                "Security testing in development and acceptance",
                "Outsourced development",
                "Separation of development, test and production environments",
                "Change management",
                "Test information",
                "Protection of information systems during audit testing",
            ],
            start=1,
        )
    ],
]

# NIST Cybersecurity Framework 2.0 (106 subcategories).
_NIST: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "GV.OC": (
        "Govern: Organizational Context",
        [
            ("01", "Organizational mission is understood and informs cybersecurity risk management"),
            ("02", "Internal and external stakeholders are understood, and their needs and expectations are considered"),
            ("03", "Legal, regulatory and contractual requirements are understood and managed"),
            ("04", "Critical objectives, capabilities and services that stakeholders depend on are understood"),
            ("05", "Outcomes, capabilities and services that the organization depends on are understood"),
        ],
    ),
    "GV.RM": (
        "Govern: Risk Management Strategy",
        [
            ("01", "Risk management objectives are established and agreed to by stakeholders"),
            ("02", "Risk appetite and risk tolerance statements are established and communicated"),
            ("03", "Cybersecurity risk management activities are included in enterprise risk management"),
            ("04", "Strategic direction describes appropriate risk response options"),
            ("05", "Lines of communication for cybersecurity risks are established"),
            ("06", "A standardized method for calculating and prioritizing cybersecurity risks is established"),
            ("07", "Strategic opportunities (positive risks) are characterized and included in risk discussions"),
        ],
    ),
    "GV.RR": (
        "Govern: Roles, Responsibilities and Authorities",
        [
            ("01", "Leadership is accountable for cybersecurity risk and fosters a culture of risk awareness"),
            ("02", "Roles, responsibilities and authorities for cybersecurity risk management are established"),
            ("03", "Adequate resources are allocated commensurate with the risk strategy"),
            ("04", "Cybersecurity is included in human resources practices"),
        ],
    ),
    "GV.PO": (
        "Govern: Policy",
        [
            ("01", "Policy for managing cybersecurity risks is established and communicated"),
            ("02", "Policy is reviewed, updated and communicated to reflect changes"),
        ],
    ),
    "GV.OV": (
        "Govern: Oversight",
        [
            ("01", "Cybersecurity risk management strategy outcomes are reviewed to inform direction"),
            ("02", "The strategy is reviewed and adjusted to ensure coverage of requirements and risks"),
            ("03", "Organizational cybersecurity risk management performance is evaluated and reviewed"),
        ],
    ),
    "GV.SC": (
        "Govern: Cybersecurity Supply Chain Risk Management",
        [
            ("01", "A cyber supply chain risk management program, strategy and policies are established"),
            ("02", "Cybersecurity roles for suppliers, customers and partners are established and coordinated"),
            ("03", "Supply chain risk management is integrated into cybersecurity and enterprise risk management"),
            ("04", "Suppliers are known and prioritized by criticality"),
            ("05", "Requirements to address supply chain risks are established and included in agreements"),
            ("06", "Planning and due diligence reduce risks before entering supplier relationships"),
            ("07", "Risks posed by a supplier are understood, recorded, prioritized and monitored"),
            ("08", "Relevant suppliers are included in incident planning, response and recovery"),
            ("09", "Supply chain security practices are integrated into the program and monitored"),
            ("10", "Cybersecurity supply chain risk management plans include post-agreement provisions"),
        ],
    ),
    "ID.AM": (
        "Identify: Asset Management",
        [
            ("01", "Inventories of hardware managed by the organization are maintained"),
            ("02", "Inventories of software, services and systems are maintained"),
            ("03", "Representations of authorized network communication and data flows are maintained"),
            ("04", "Inventories of services provided by suppliers are maintained"),
            ("05", "Assets are prioritized based on classification, criticality, resources and impact"),
            ("07", "Inventories of data and corresponding metadata are maintained"),
            ("08", "Systems, hardware, software, services and data are managed throughout their life cycles"),
        ],
    ),
    "ID.RA": (
        "Identify: Risk Assessment",
        [
            ("01", "Vulnerabilities in assets are identified, validated and recorded"),
            ("02", "Cyber threat intelligence is received from information sharing forums and sources"),
            ("03", "Internal and external threats to the organization are identified and recorded"),
            ("04", "Potential impacts and likelihoods of threats exploiting vulnerabilities are identified"),
            ("05", "Threats, vulnerabilities, likelihoods and impacts are used to understand inherent risk"),
            ("06", "Risk responses are chosen, prioritized, planned, tracked and communicated"),
            ("07", "Changes and exceptions are managed, assessed for risk impact, recorded and tracked"),
            ("08", "Processes for receiving, analyzing and responding to vulnerability disclosures are established"),
            ("09", "The authenticity and integrity of hardware and software are assessed prior to acquisition"),
            ("10", "Critical suppliers are assessed prior to acquisition"),
        ],
    ),
    "ID.IM": (
        "Identify: Improvement",
        [
            ("01", "Improvements are identified from evaluations"),
            ("02", "Improvements are identified from security tests and exercises, including with suppliers"),
            ("03", "Improvements are identified from execution of operational processes, procedures and activities"),
            ("04", "Incident response plans and other cybersecurity plans are established, communicated and improved"),
        ],
    ),
    "PR.AA": (
        "Protect: Identity Management, Authentication and Access Control",
        [
            ("01", "Identities and credentials for authorized users, services and hardware are managed"),
            ("02", "Identities are proofed and bound to credentials based on the context of interactions"),
            ("03", "Users, services and hardware are authenticated"),
            ("04", "Identity assertions are protected, conveyed and verified"),
            ("05", "Access permissions and authorizations are defined and managed (least privilege, separation of duties)"),
            ("06", "Physical access to assets is managed, monitored and enforced"),
        ],
    ),
    "PR.AT": (
        "Protect: Awareness and Training",
        [
            ("01", "Personnel are provided with awareness and training to possess the knowledge and skills for general tasks"),
            ("02", "Individuals in specialized roles are provided with awareness and training for their tasks"),
        ],
    ),
    "PR.DS": (
        "Protect: Data Security",
        [
            ("01", "The confidentiality, integrity and availability of data-at-rest are protected"),
            ("02", "The confidentiality, integrity and availability of data-in-transit are protected"),
            ("10", "The confidentiality, integrity and availability of data-in-use are protected"),
            ("11", "Backups of data are created, protected, maintained and tested"),
        ],
    ),
    "PR.PS": (
        "Protect: Platform Security",
        [
            ("01", "Configuration management practices are established and applied"),
            ("02", "Software is maintained, replaced and removed commensurate with risk"),
            ("03", "Hardware is maintained, replaced and removed commensurate with risk"),
            ("04", "Log records are generated and made available for continuous monitoring"),
            ("05", "Installation and execution of unauthorized software are prevented"),
            ("06", "Secure software development practices are integrated and their performance is monitored"),
        ],
    ),
    "PR.IR": (
        "Protect: Technology Infrastructure Resilience",
        [
            ("01", "Networks and environments are protected from unauthorized logical access and usage"),
            ("02", "The organization's technology assets are protected from environmental threats"),
            ("03", "Mechanisms are implemented to achieve resilience requirements in normal and adverse situations"),
            ("04", "Adequate resource capacity to ensure availability is maintained"),
        ],
    ),
    "DE.CM": (
        "Detect: Continuous Monitoring",
        [
            ("01", "Networks and network services are monitored to find potentially adverse events"),
            ("02", "The physical environment is monitored to find potentially adverse events"),
            ("03", "Personnel activity and technology usage are monitored to find potentially adverse events"),
            ("06", "External service provider activities and services are monitored to find potentially adverse events"),
            ("09", "Computing hardware and software, runtime environments and their data are monitored"),
        ],
    ),
    "DE.AE": (
        "Detect: Adverse Event Analysis",
        [
            ("02", "Potentially adverse events are analyzed to better understand associated activities"),
            ("03", "Information is correlated from multiple sources"),
            ("04", "The estimated impact and scope of adverse events are understood"),
            ("06", "Information on adverse events is provided to authorized staff and tools"),
            ("07", "Cyber threat intelligence and other contextual information are integrated into the analysis"),
            ("08", "Incidents are declared when adverse events meet the defined incident criteria"),
        ],
    ),
    "RS.MA": (
        "Respond: Incident Management",
        [
            ("01", "The incident response plan is executed in coordination with relevant third parties"),
            ("02", "Incident reports are triaged and validated"),
            ("03", "Incidents are categorized and prioritized"),
            ("04", "Incidents are escalated or elevated as needed"),
            ("05", "The criteria for initiating incident recovery are applied"),
        ],
    ),
    "RS.AN": (
        "Respond: Incident Analysis",
        [
            ("03", "Analysis is performed to establish what has taken place during an incident and the root cause"),
            ("06", "Actions performed during an investigation are recorded and their integrity and provenance preserved"),
            ("07", "Incident data and metadata are collected and their integrity and provenance preserved"),
            ("08", "An incident's magnitude is estimated and validated"),
        ],
    ),
    "RS.CO": (
        "Respond: Incident Response Reporting and Communication",
        [
            ("02", "Internal and external stakeholders are notified of incidents"),
            ("03", "Information is shared with designated internal and external stakeholders"),
        ],
    ),
    "RS.MI": (
        "Respond: Incident Mitigation",
        [
            ("01", "Incidents are contained"),
            ("02", "Incidents are eradicated"),
        ],
    ),
    "RC.RP": (
        "Recover: Incident Recovery Plan Execution",
        [
            ("01", "The recovery portion of the incident response plan is executed once initiated"),
            ("02", "Recovery actions are selected, scoped, prioritized and performed"),
            ("03", "The integrity of backups and other restoration assets is verified before use"),
            ("04", "Critical mission functions and cybersecurity risk management are considered to establish post-incident norms"),
            (
                "05",
                "The integrity of restored assets is verified, systems and services are restored, and normal operating status is confirmed",
            ),
            ("06", "The end of incident recovery is declared based on criteria, and incident-related documentation is completed"),
        ],
    ),
    "RC.CO": (
        "Recover: Incident Recovery Communication",
        [
            ("03", "Recovery activities and progress in restoring normal operations are communicated to stakeholders"),
            ("04", "Public updates on incident recovery are shared using approved methods and messaging"),
        ],
    ),
}
NIST_CSF: Catalog = [(group, f"{cat}-{n}", title) for cat, (group, rows) in _NIST.items() for n, title in rows]

# PCI DSS v4.0: each principal requirement, then its second-level requirements.
_PCI: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Install and maintain network security controls",
        [
            "Processes and mechanisms for network security controls are defined and understood",
            "Network security controls are configured and maintained",
            "Network access to and from the cardholder data environment is restricted",
            "Network connections between trusted and untrusted networks are controlled",
            "Risks to the CDE from computing devices that connect to both untrusted networks and the CDE are mitigated",
        ],
    ),
    (
        2,
        "Apply secure configurations to all system components",
        [
            "Processes and mechanisms for applying secure configurations are defined and understood",
            "System components are configured and managed securely",
            "Wireless environments are configured and managed securely",
        ],
    ),
    (
        3,
        "Protect stored account data",
        [
            "Processes and mechanisms for protecting stored account data are defined and understood",
            "Storage of account data is kept to a minimum",
            "Sensitive authentication data is not stored after authorization",
            "Access to displays of full PAN and ability to copy cardholder data are restricted",
            "Primary account number (PAN) is secured wherever it is stored",
            "Cryptographic keys used to protect stored account data are secured",
            "Where cryptography is used to protect stored account data, key management processes are defined and implemented",
        ],
    ),
    (
        4,
        "Protect cardholder data with strong cryptography during transmission over open, public networks",
        [
            "Processes and mechanisms for protecting cardholder data in transit are defined and understood",
            "PAN is protected with strong cryptography during transmission",
        ],
    ),
    (
        5,
        "Protect all systems and networks from malicious software",
        [
            "Processes and mechanisms for protecting systems from malicious software are defined and understood",
            "Malicious software is prevented, or detected and addressed",
            "Anti-malware mechanisms and processes are active, maintained and monitored",
            "Anti-phishing mechanisms protect users against phishing attacks",
        ],
    ),
    (
        6,
        "Develop and maintain secure systems and software",
        [
            "Processes and mechanisms for developing and maintaining secure systems and software are defined and understood",
            "Bespoke and custom software is developed securely",
            "Security vulnerabilities are identified and addressed",
            "Public-facing web applications are protected against attacks",
            "Changes to all system components are managed securely",
        ],
    ),
    (
        7,
        "Restrict access to system components and cardholder data by business need to know",
        [
            "Processes and mechanisms for restricting access by business need to know are defined and understood",
            "Access to system components and data is appropriately defined and assigned",
            "Access to system components and data is managed via an access control system",
        ],
    ),
    (
        8,
        "Identify users and authenticate access to system components",
        [
            "Processes and mechanisms for identifying users and authenticating access are defined and understood",
            "User identification and related accounts for users and administrators are strictly managed",
            "Strong authentication for users and administrators is established and managed",
            "Multi-factor authentication (MFA) is implemented to secure access into the CDE",
            "MFA systems are configured to prevent misuse",
            "Use of application and system accounts and associated authentication factors is strictly managed",
        ],
    ),
    (
        9,
        "Restrict physical access to cardholder data",
        [
            "Processes and mechanisms for restricting physical access are defined and understood",
            "Physical access controls manage entry into facilities and systems containing cardholder data",
            "Physical access for personnel and visitors is authorized and managed",
            "Media with cardholder data is securely stored, accessed, distributed and destroyed",
            "Point of interaction (POI) devices are protected from tampering and unauthorized substitution",
        ],
    ),
    (
        10,
        "Log and monitor all access to system components and cardholder data",
        [
            "Processes and mechanisms for logging and monitoring all access are defined and documented",
            "Audit logs are implemented to support the detection of anomalies and suspicious activity",
            "Audit logs are protected from destruction and unauthorized modifications",
            "Audit logs are reviewed to identify anomalies or suspicious activity",
            "Audit log history is retained and available for analysis",
            "Time-synchronization mechanisms support consistent time settings across all systems",
            "Failures of critical security control systems are detected, reported and responded to promptly",
        ],
    ),
    (
        11,
        "Test security of systems and networks regularly",
        [
            "Processes and mechanisms for regularly testing security are defined and understood",
            "Wireless access points are identified and monitored, and unauthorized wireless access points are addressed",
            "External and internal vulnerabilities are regularly identified, prioritized and addressed",
            "External and internal penetration testing is regularly performed",
            "Network intrusions and unexpected file changes are detected and responded to",
            "Unauthorized changes on payment pages are detected and responded to",
        ],
    ),
    (
        12,
        "Support information security with organizational policies and programs",
        [
            "A comprehensive information security policy is known and current",
            "Acceptable use policies for end-user technologies are defined and implemented",
            "Risks to the cardholder data environment are formally identified, evaluated and managed",
            "PCI DSS compliance is managed",
            "PCI DSS scope is documented and validated",
            "Security awareness education is an ongoing activity",
            "Personnel are screened to reduce risks from insider threats",
            "Risk to information assets associated with third-party service provider relationships is managed",
            "Third-party service providers support their customers' PCI DSS compliance",
            "Suspected and confirmed security incidents that could impact the CDE are responded to immediately",
        ],
    ),
]
PCI_DSS: Catalog = []
for _num, _title, _subs in _PCI:
    _group = f"Requirement {_num}: {_title}"
    PCI_DSS.append((_group, f"Req-{_num}", _title))
    PCI_DSS.extend((_group, f"Req-{_num}.{i}", sub) for i, sub in enumerate(_subs, start=1))

# HIPAA Security Rule (45 CFR 164.308 to 164.316): each standard, then its implementation specifications.
_A, _P, _T, _O, _D = (
    "Administrative safeguards (164.308)",
    "Physical safeguards (164.310)",
    "Technical safeguards (164.312)",
    "Organizational requirements (164.314)",
    "Policies and documentation (164.316)",
)
HIPAA: Catalog = [
    (_A, "164.308(a)(1)", "Security management process"),
    (_A, "164.308(a)(1)(ii)(A)", "Risk analysis"),
    (_A, "164.308(a)(1)(ii)(B)", "Risk management"),
    (_A, "164.308(a)(1)(ii)(C)", "Sanction policy"),
    (_A, "164.308(a)(1)(ii)(D)", "Information system activity review"),
    (_A, "164.308(a)(2)", "Assigned security responsibility"),
    (_A, "164.308(a)(3)", "Workforce security"),
    (_A, "164.308(a)(3)(ii)(A)", "Authorization and/or supervision"),
    (_A, "164.308(a)(3)(ii)(B)", "Workforce clearance procedure"),
    (_A, "164.308(a)(3)(ii)(C)", "Termination procedures"),
    (_A, "164.308(a)(4)", "Information access management"),
    (_A, "164.308(a)(4)(ii)(A)", "Isolating health care clearinghouse functions"),
    (_A, "164.308(a)(4)(ii)(B)", "Access authorization"),
    (_A, "164.308(a)(4)(ii)(C)", "Access establishment and modification"),
    (_A, "164.308(a)(5)", "Security awareness and training"),
    (_A, "164.308(a)(5)(ii)(A)", "Security reminders"),
    (_A, "164.308(a)(5)(ii)(B)", "Protection from malicious software"),
    (_A, "164.308(a)(5)(ii)(C)", "Log-in monitoring"),
    (_A, "164.308(a)(5)(ii)(D)", "Password management"),
    (_A, "164.308(a)(6)", "Security incident procedures"),
    (_A, "164.308(a)(6)(ii)", "Response and reporting"),
    (_A, "164.308(a)(7)", "Contingency plan"),
    (_A, "164.308(a)(7)(ii)(A)", "Data backup plan"),
    (_A, "164.308(a)(7)(ii)(B)", "Disaster recovery plan"),
    (_A, "164.308(a)(7)(ii)(C)", "Emergency mode operation plan"),
    (_A, "164.308(a)(7)(ii)(D)", "Testing and revision procedures"),
    (_A, "164.308(a)(7)(ii)(E)", "Applications and data criticality analysis"),
    (_A, "164.308(a)(8)", "Evaluation"),
    (_A, "164.308(b)(1)", "Business associate contracts and other arrangements"),
    (_A, "164.308(b)(3)", "Written contract or other arrangement"),
    (_P, "164.310(a)(1)", "Facility access controls"),
    (_P, "164.310(a)(2)(i)", "Contingency operations"),
    (_P, "164.310(a)(2)(ii)", "Facility security plan"),
    (_P, "164.310(a)(2)(iii)", "Access control and validation procedures"),
    (_P, "164.310(a)(2)(iv)", "Maintenance records"),
    (_P, "164.310(b)", "Workstation use"),
    (_P, "164.310(c)", "Workstation security"),
    (_P, "164.310(d)(1)", "Device and media controls"),
    (_P, "164.310(d)(2)(i)", "Disposal"),
    (_P, "164.310(d)(2)(ii)", "Media re-use"),
    (_P, "164.310(d)(2)(iii)", "Accountability"),
    (_P, "164.310(d)(2)(iv)", "Data backup and storage"),
    (_T, "164.312(a)(1)", "Access control"),
    (_T, "164.312(a)(2)(i)", "Unique user identification"),
    (_T, "164.312(a)(2)(ii)", "Emergency access procedure"),
    (_T, "164.312(a)(2)(iii)", "Automatic logoff"),
    (_T, "164.312(a)(2)(iv)", "Encryption and decryption"),
    (_T, "164.312(b)", "Audit controls"),
    (_T, "164.312(c)(1)", "Integrity"),
    (_T, "164.312(c)(2)", "Mechanism to authenticate electronic protected health information"),
    (_T, "164.312(d)", "Person or entity authentication"),
    (_T, "164.312(e)(1)", "Transmission security"),
    (_T, "164.312(e)(2)(i)", "Integrity controls"),
    (_T, "164.312(e)(2)(ii)", "Encryption"),
    (_O, "164.314(a)(1)", "Business associate contracts or other arrangements"),
    (_O, "164.314(a)(2)", "Business associate contract requirements"),
    (_O, "164.314(b)(1)", "Requirements for group health plans"),
    (_O, "164.314(b)(2)", "Group health plan implementation specifications"),
    (_D, "164.316(a)", "Policies and procedures"),
    (_D, "164.316(b)(1)", "Documentation"),
    (_D, "164.316(b)(2)(i)", "Time limit"),
    (_D, "164.316(b)(2)(ii)", "Availability"),
    (_D, "164.316(b)(2)(iii)", "Updates"),
]

CATALOGS: dict[str, Catalog] = {"SOC2": SOC2, "ISO27001": ISO27001, "NIST-CSF": NIST_CSF, "PCI-DSS": PCI_DSS, "HIPAA": HIPAA}
