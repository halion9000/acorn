"""What each control of a compliance framework means in plain words, what has to be in place to meet it, and what to attach as evidence.

The control titles in ``compliance_catalog`` are short and say what the criterion is about, not what a company has to do. This says the rest, for the SOC 2 Trust Services Criteria (the 61
controls of that page), and since 2026-11-13 for HIPAA (63) and NIST CSF 2.0 (106). It is guidance written for this page, in A.C.O.R.N's own words: it is not the AICPA's text and not an auditor's opinion. An auditor decides what is enough for a
given company; this is the usual shape of "enough" for a small or mid-sized service organisation, so a control is never left as a title and an empty evidence box.

Each entry is ``(meaning, what it takes, evidence to attach)``. Frameworks not listed here have no guidance yet and their controls show none.
"""

from __future__ import annotations

from typing import NamedTuple

from app.services import compliance_guidance_hipaa as _hipaa
from app.services import compliance_guidance_nist_gi as _nist_gi
from app.services import compliance_guidance_nist_pr as _nist_pr


class Guidance(NamedTuple):
    meaning: str
    to_meet: tuple[str, ...]
    evidence: tuple[str, ...]


def _g(meaning: str, to_meet: list[str], evidence: list[str]) -> Guidance:
    return Guidance(meaning, tuple(to_meet), tuple(evidence))


SOC2: dict[str, Guidance] = {
    # ---- CC1 Control environment
    "CC1.1": _g(
        "The company says how its people are expected to behave, and acts when they do not.",
        [
            "A code of conduct that every employee and contractor signs when they join and again each year",
            "Background checks before a new hire gets access, where the law allows",
            "A way to report a concern without fear (a named contact or an anonymous channel)",
            "A written disciplinary process for breaking the code or a security policy",
        ],
        [
            "The code of conduct with its approval date",
            "Signed acknowledgements for a sample of staff",
            "A background check record for a recent hire (details redacted)",
            "The disciplinary policy",
        ],
    ),
    "CC1.2": _g(
        "Someone independent of day-to-day management oversees security and internal control: a board, an advisory board, or the owners meeting for that purpose.",
        [
            "A named oversight body with at least one member who does not run operations (for a small company: the owners with an outside adviser)",
            "It meets on a schedule (at least yearly, usually quarterly) and security, risk and audit results are on the agenda",
            "A short charter saying what it is responsible for",
        ],
        [
            "The charter or the section of the bylaws",
            "Minutes of the last meetings showing security and risk were discussed",
            "The list of members and their roles",
        ],
    ),
    "CC1.3": _g(
        "It is clear who reports to whom and who is responsible for what, including for security.",
        [
            "A current organisation chart",
            "Written job descriptions for the roles that touch systems and customer data",
            "A named person responsible for security, and one for each key control (access, change, backup, incident response)",
        ],
        [
            "The organisation chart with its date",
            "Job descriptions for security-relevant roles",
            "A roles and responsibilities matrix (who owns which control)",
        ],
    ),
    "CC1.4": _g(
        "The company hires people who can do the job, trains them, and checks they stay competent.",
        [
            "Hiring that checks skills for the role (interview notes, references)",
            "Security awareness training at onboarding and every year, with completion tracked",
            "Role training for technical staff (for example secure administration for engineers)",
            "Performance reviews at least yearly",
        ],
        [
            "Training completion report for the year",
            "The onboarding checklist for a recent hire",
            "A sample performance review record (details redacted)",
        ],
    ),
    "CC1.5": _g(
        "People are held accountable for the controls they own.",
        [
            "Control owners are named and know it",
            "Control duties are part of job descriptions or objectives",
            "Performance reviews consider whether those duties were carried out",
            "Policy breaches lead to documented follow-up",
        ],
        [
            "The control owner list",
            "A job description or objective that names a control duty",
            "A record of follow-up on a policy breach, if there was one",
        ],
    ),
    # ---- CC2 Communication and information
    "CC2.1": _g(
        "The information used to run controls is accurate, complete and on time: logs, asset lists, user lists, ticket data.",
        [
            "An inventory of systems and where their data comes from",
            "Logs and monitoring data collected centrally and kept for a set time",
            "Checks that key reports are complete (for example the user list matches the HR list)",
        ],
        [
            "The system and data inventory",
            "Log retention settings",
            "A reconciliation of a key report (user access against HR, assets against the device tool)",
        ],
    ),
    "CC2.2": _g(
        "Staff know the security policies, their own duties, and how to raise a problem.",
        [
            "Security policies published where every employee can read them",
            "Policies acknowledged at hire and when they change",
            "A known way to report a security incident or concern internally",
            "Changes that affect controls are announced to the people they affect",
        ],
        [
            "Where the policies are published (screenshot)",
            "Policy acknowledgement records",
            "The incident reporting instructions given to staff",
            "An example announcement of a change",
        ],
    ),
    "CC2.3": _g(
        "Customers, vendors and other outside parties are told what the company commits to and how to reach it about security.",
        [
            "Customer contracts or terms that state security and confidentiality commitments",
            "A public contact for reporting a security problem (an address or a web form)",
            "A way to tell customers about incidents and important changes (status page, e-mail list)",
            "A description of the service and its boundaries for customers and the auditor",
        ],
        [
            "A customer agreement template with the security terms",
            "The security contact page",
            "The system description",
            "An example customer notice",
        ],
    ),
    # ---- CC3 Risk assessment
    "CC3.1": _g(
        "The company states what it is trying to achieve (service commitments, legal duties) clearly enough that risks to it can be named.",
        [
            "Written service commitments and system requirements (uptime, confidentiality, response times)",
            "The laws, regulations and contracts that apply, listed",
            "Risk tolerance stated by management (what level of risk is acceptable)",
        ],
        [
            "The service commitments document",
            "The list of legal and contractual obligations",
            "The risk management policy with the risk tolerance",
        ],
    ),
    "CC3.2": _g(
        "Risks to those objectives are identified, rated and given an owner, and it is redone regularly.",
        [
            "A risk assessment at least once a year and after a major change",
            "A risk register: each risk with likelihood, impact, owner and treatment",
            "Threats from vendors, people, technology and the environment all considered",
            "Treatment plans tracked until done",
        ],
        ["The latest risk assessment with its date", "The risk register", "Evidence that a treatment plan was followed up"],
    ),
    "CC3.3": _g(
        "The risk assessment thinks about fraud: how someone inside or outside could cheat, steal or hide something.",
        [
            "Fraud scenarios in the risk register (misuse of admin access, false invoices, changed records)",
            "Duties separated where one person could both do and hide a wrong act",
            "Incentives and pressures considered (targets, access to money or data)",
        ],
        ["The fraud section of the risk assessment", "A separation of duties matrix"],
    ),
    "CC3.4": _g(
        "Changes that could weaken controls are noticed and assessed: new systems, new vendors, new laws, reorganisations, acquisitions.",
        [
            "The risk assessment is revisited when something significant changes, not only yearly",
            "New systems and vendors get a security review before they are used",
            "Someone watches for changes in laws and contracts that apply",
        ],
        ["A risk review triggered by a change (a new system or vendor)", "The change or project checklist that includes a risk review"],
    ),
    # ---- CC4 Monitoring activities
    "CC4.1": _g(
        "The company checks that its controls are in place and working, continuously or at set times.",
        [
            "Automated monitoring of key controls (configuration, access, backups, endpoint protection)",
            "Periodic reviews: access reviews, vulnerability scans, a penetration test at least yearly",
            "Internal audit or self-assessment of controls at least yearly",
        ],
        [
            "Monitoring dashboards or reports",
            "The latest penetration test report",
            "The latest vulnerability scan",
            "The internal control review with its date",
        ],
    ),
    "CC4.2": _g(
        "When a control is found not working, it is reported to the people who must fix it and to management, and fixed in a set time.",
        [
            "Findings from scans, tests and audits logged as tickets with an owner and a due date",
            "Management sees open findings on a schedule",
            "Fix times defined by severity, and overdue items escalated",
        ],
        [
            "The findings tracker",
            "Tickets showing a finding fixed within its time",
            "Management meeting notes where open findings were reviewed",
        ],
    ),
    # ---- CC5 Control activities
    "CC5.1": _g(
        "Controls are chosen to bring the identified risks down to an acceptable level.",
        [
            "Each significant risk in the register is linked to the controls that reduce it",
            "A mix of preventive and detective controls, manual and automated",
            "Duties separated for sensitive tasks",
        ],
        ["The risk register with the mapped controls", "The control list (control matrix)"],
    ),
    "CC5.2": _g(
        "General technology controls are in place: access, change management, operations and security of the infrastructure that the service runs on.",
        [
            "Access control over infrastructure and tools (single sign-on, multi-factor sign-in, least privilege)",
            "Change management for code and infrastructure",
            "Backup, monitoring and patching of the systems in scope",
            "Security requirements when technology is bought or built",
        ],
        [
            "The access control, change management and operations policies",
            "Settings showing multi-factor sign-in is required",
            "Patch and backup reports",
        ],
    ),
    "CC5.3": _g(
        "Controls are written down as policies and procedures, and people follow them.",
        [
            "A set of approved security policies, each with an owner",
            "Policies reviewed and re-approved at least once a year",
            "Procedures that say how a policy is carried out day to day",
            "Exceptions to policy recorded and approved",
        ],
        [
            "The policy set with version, owner and approval date",
            "The record of the yearly policy review",
            "An approved policy exception, if any",
        ],
    ),
    # ---- CC6 Logical and physical access
    "CC6.1": _g(
        "Access to systems and data is protected by technical means: identities, authentication, network boundaries and encryption.",
        [
            "Every user and service has its own identity; no shared accounts for people",
            "Multi-factor sign-in on everything that holds company or customer data",
            "Password rules, or single sign-on with a strong identity provider",
            "Data encrypted at rest and in transit; keys and secrets managed",
            "Networks segmented and firewalled; an inventory of the systems in scope",
        ],
        [
            "The identity provider's multi-factor and password settings",
            "Encryption settings for databases, disks and connections",
            "The network diagram and firewall rules",
            "The asset inventory",
        ],
    ),
    "CC6.2": _g(
        "Access is given only after it is requested and approved, and taken away when the person leaves or no longer needs it.",
        [
            "Access requests recorded and approved by the manager or system owner before access is granted",
            "Leavers' access removed within a set time (usually one business day)",
            "Onboarding and offboarding checklists",
            "No access granted outside the process",
        ],
        [
            "Access request tickets with approvals for a sample of new users",
            "Offboarding tickets for a sample of leavers with the time access was removed",
            "The onboarding and offboarding checklists",
        ],
    ),
    "CC6.3": _g(
        "People have only the access their role needs, it changes when the role changes, and it is reviewed.",
        [
            "Roles defined per system, with least privilege",
            "Administrator access limited to the few who need it",
            "User access reviews at least quarterly for sensitive systems, with removals carried out",
            "Access changed when someone moves role",
        ],
        [
            "The role definitions",
            "The list of administrators with justification",
            "The last access reviews with their sign-off and the removals that followed",
        ],
    ),
    "CC6.4": _g(
        "Only authorised people can physically get to offices, server rooms and equipment that hold data.",
        [
            "Doors locked and entry by badge or key issued to named people",
            "Visitors signed in and escorted",
            "Server rooms or network closets restricted to named staff",
            "For cloud-hosted systems: the provider's own audit report covers the data centres",
        ],
        ["The badge or key holder list", "A visitor log", "The cloud provider's SOC 2 or ISO 27001 report", "The physical security policy"],
    ),
    "CC6.5": _g(
        "Equipment and media are wiped or destroyed before they are thrown away, sold or reused, so data cannot be recovered.",
        [
            "A disposal procedure: wipe to a recognised standard or physically destroy",
            "A record of each disposal: what, when, how, by whom",
            "Certificates of destruction from the disposal vendor",
            "Data deleted when a customer leaves, as the contract says",
        ],
        ["The media disposal policy", "The disposal log", "A certificate of destruction", "A customer data deletion record"],
    ),
    "CC6.6": _g(
        "Systems are protected from attack from outside: the internet, partner connections, remote access.",
        [
            "Firewalls or security groups that allow only what is needed; no management ports open to the internet",
            "Remote access through a VPN or zero-trust tool with multi-factor sign-in",
            "Web applications protected (web application firewall, rate limits)",
            "Intrusion detection or managed detection on the perimeter and endpoints",
            "External vulnerability scans and a yearly penetration test",
        ],
        [
            "Firewall or security group rules",
            "Remote access configuration",
            "The external scan and penetration test reports",
            "The detection tool's coverage report",
        ],
    ),
    "CC6.7": _g(
        "Data is protected when it moves: sent, copied to laptops or removable media, or taken out of the company.",
        [
            "Encryption in transit (TLS) for everything sent over networks",
            "Laptops and phones encrypted and managed (device management)",
            "Removable media blocked or encrypted",
            "Rules or tools to stop sensitive data being sent out wrongly (data loss prevention)",
        ],
        [
            "TLS configuration or scan result",
            "Device encryption report from the device management tool",
            "The removable media setting",
            "Data loss prevention rules",
        ],
    ),
    "CC6.8": _g(
        "Malware and unauthorised software are kept out, and found if they get in.",
        [
            "Endpoint protection (antivirus or EDR) on every workstation and server, reporting centrally",
            "Users cannot install software freely (no local admin rights, or an approval tool)",
            "E-mail and web filtering",
            "Alerts from these tools are looked at and acted on",
        ],
        [
            "Endpoint protection coverage report (every device, agent healthy)",
            "The local administrator policy",
            "E-mail and web filter settings",
            "A handled malware alert",
        ],
    ),
    # ---- CC7 System operations
    "CC7.1": _g(
        "The company notices when a configuration changes in a way it should not, and when new vulnerabilities appear.",
        [
            "Secure configuration baselines for servers, workstations and cloud accounts",
            "Monitoring that flags drift from the baseline",
            "Vulnerability scanning on a schedule (at least monthly) inside and outside",
            "Patches applied within set times by severity",
        ],
        [
            "The configuration baselines",
            "A drift or configuration monitoring report",
            "The last vulnerability scans",
            "Patch compliance report",
        ],
    ),
    "CC7.2": _g(
        "Systems are watched for signs of attack, misuse or failure, and the alerts reach someone.",
        [
            "Logs from key systems collected in one place and kept (usually a year)",
            "Alerts for suspicious sign-ins, privilege changes, malware and availability problems",
            "Someone is responsible for looking at alerts, with defined response times",
            "Monitoring covers the whole scope, with no blind spots",
        ],
        [
            "The list of log sources",
            "The alert rules in the monitoring tool",
            "Evidence that alerts were triaged (tickets, response times)",
            "Log retention settings",
        ],
    ),
    "CC7.3": _g(
        "Security events are assessed to decide whether they are incidents, and how serious.",
        [
            "A written way to classify events (severity levels and what makes an incident)",
            "Each alert investigated and the conclusion recorded",
            "Escalation rules: who is told at which severity",
        ],
        [
            "The incident classification section of the incident response plan",
            "A sample of investigated alerts with their conclusions",
            "The escalation matrix",
        ],
    ),
    "CC7.4": _g(
        "When there is an incident, the company contains it, removes the cause, tells who must be told, and learns from it.",
        [
            "An incident response plan with roles, steps and contact lists",
            "Incidents recorded from detection to closure",
            "Customers, regulators and others notified when the contract or law requires",
            "A review after each significant incident, with actions followed up",
            "The plan tested at least once a year (a tabletop exercise)",
        ],
        [
            "The incident response plan",
            "An incident record with its timeline",
            "A post-incident review",
            "The record of the last tabletop exercise",
        ],
    ),
    "CC7.5": _g(
        "After an incident, systems and data are restored and the weakness that allowed it is fixed.",
        [
            "Recovery steps in the incident response or disaster recovery plan",
            "Restores from backup when needed, and verification that the restored system is clean",
            "Root cause fixed and controls improved",
        ],
        ["A recovery record for an incident", "A backup restore test", "The changes made after an incident"],
    ),
    # ---- CC8 Change management
    "CC8.1": _g(
        "Changes to software, infrastructure and configuration are requested, reviewed, tested and approved before they go live, and can be undone.",
        [
            "Every change tracked (ticket or pull request) with what and why",
            "Review and approval by someone other than the author before release",
            "Testing before production; separate test and production environments",
            "Production access limited, and emergency changes reviewed afterwards",
            "A way to roll back",
        ],
        [
            "The change management policy",
            "A sample of changes with review, test and approval",
            "Branch protection or deployment settings",
            "An emergency change with its after-the-fact review",
        ],
    ),
    # ---- CC9 Risk mitigation
    "CC9.1": _g(
        "The company prepares for things that could interrupt the business: outages, disasters, loss of key people or suppliers.",
        [
            "A business continuity and disaster recovery plan",
            "Recovery time and recovery point targets for key systems",
            "The plan tested at least yearly",
            "Insurance that covers cyber incidents and business interruption",
        ],
        ["The business continuity and disaster recovery plan", "The last test with its results", "The cyber insurance certificate"],
    ),
    "CC9.2": _g(
        "Vendors and partners that could affect security are checked before they are used and watched while they are.",
        [
            "A list of vendors with what data or access each has and how critical it is",
            "Security review before signing a vendor that handles data (their SOC 2 or ISO report, a questionnaire)",
            "Contracts with security, confidentiality and breach-notification terms",
            "Critical vendors reviewed again every year",
        ],
        [
            "The vendor inventory with risk ratings",
            "A vendor security review",
            "A vendor's SOC 2 report and the review of it",
            "A contract with the security terms",
        ],
    ),
    # ---- A1 Availability
    "A1.1": _g(
        "Capacity is watched and planned so the service does not run out of processing, storage or network.",
        [
            "Monitoring of capacity and performance with alerts before limits are reached",
            "Capacity reviewed on a schedule and before big changes",
            "Scaling or procurement when forecasts say so",
        ],
        ["Capacity dashboards", "Capacity alerts", "A capacity review or forecast"],
    ),
    "A1.2": _g(
        "The systems are protected from environmental threats and backed up, with what is needed to recover.",
        [
            "Backups of data and configuration on a schedule, encrypted, with a copy off-site or in another region",
            "Backup jobs monitored and failures fixed",
            "Redundancy for key components (power, network, servers or cloud zones)",
            "For hosted systems: the provider's report covers power, cooling and fire protection",
        ],
        [
            "Backup configuration and schedule",
            "Backup success reports",
            "The architecture diagram showing redundancy",
            "The data centre or cloud provider's audit report",
        ],
    ),
    "A1.3": _g(
        "Recovery is tested: the company proves it can restore within its targets.",
        [
            "A restore test at least once a year (more often for critical data)",
            "A disaster recovery exercise against the recovery time and recovery point targets",
            "Problems found in tests are fixed",
        ],
        ["The last restore test with timings", "The disaster recovery exercise report", "Follow-up actions from the test"],
    ),
    # ---- C1 Confidentiality
    "C1.1": _g(
        "Confidential information is identified and protected for as long as it is kept.",
        [
            "A data classification policy (what is confidential) and an inventory of where such data is",
            "Access to confidential data limited to those who need it, and encrypted",
            "Confidentiality agreements with staff, contractors and vendors",
            "Retention periods set",
        ],
        [
            "The data classification policy",
            "The data inventory or data flow diagram",
            "A signed confidentiality agreement",
            "Access lists for a confidential data store",
        ],
    ),
    "C1.2": _g(
        "Confidential information is destroyed when it is no longer needed or when the customer asks.",
        [
            "A retention and disposal schedule",
            "Deletion carried out and recorded when retention ends or a contract ends",
            "Deletion covers backups and copies within a stated time",
        ],
        ["The retention and disposal policy", "A deletion record", "A customer offboarding record showing data removed"],
    ),
    # ---- PI1 Processing integrity
    "PI1.1": _g(
        "What the system is supposed to do with data is defined and communicated: what correct, complete and timely processing means.",
        [
            "Documented processing requirements and data definitions for the service",
            "These are available to the people who build and run it, and to customers where relevant",
        ],
        ["Service or product specifications", "Data definitions", "Customer-facing documentation of processing commitments"],
    ),
    "PI1.2": _g(
        "Data going into the system is checked so that it is complete, accurate and authorised.",
        [
            "Input validation in the application and its interfaces",
            "Rejected or failed inputs logged and followed up",
            "Only authorised sources can submit data",
        ],
        ["Validation rules or tests", "An error log with follow-up", "Interface authentication settings"],
    ),
    "PI1.3": _g(
        "Processing does what it should: complete, accurate, on time, and errors are caught.",
        [
            "Automated tests of processing logic",
            "Monitoring of jobs and queues, with alerts for failures and delays",
            "Errors investigated and corrected, with a record",
        ],
        ["Test results", "Job monitoring dashboards", "An incident or ticket for a processing error and its fix"],
    ),
    "PI1.4": _g(
        "Outputs are complete and accurate and go only to those meant to receive them.",
        ["Output checks or reconciliations", "Access control over reports and exports", "Delivery to the right recipient verified"],
        ["A reconciliation of output against input", "Access settings for reports and exports"],
    ),
    "PI1.5": _g(
        "Stored data stays complete and accurate: inputs, work in progress and outputs.",
        [
            "Databases protected from unauthorised change (access control, audit logs)",
            "Backups and integrity checks",
            "Retention as specified",
        ],
        ["Database access and audit settings", "Backup and integrity check reports", "The retention configuration"],
    ),
    # ---- Privacy
    "P1.1": _g(
        "People are told, in plain words, what personal information is collected, why, and what is done with it.",
        [
            "A privacy notice published where data is collected",
            "It is kept up to date and dated",
            "It covers purposes, sharing, retention, rights and contact details",
        ],
        ["The privacy notice with its date and history of changes", "Where it is shown (screenshots)"],
    ),
    "P2.1": _g(
        "People are given choices about their personal information, and consent is obtained where it is needed.",
        [
            "Consent collected before use where the law or the notice requires it",
            "A way to withdraw consent or opt out",
            "Consent recorded",
        ],
        ["The consent mechanism (screenshots)", "Consent records", "The opt-out process"],
    ),
    "P3.1": _g(
        "Only the personal information needed for the stated purposes is collected, by fair and lawful means.",
        ["A record of what personal data is collected and why (data map)", "Collection limited to that; new collection reviewed first"],
        ["The personal data inventory or record of processing", "A privacy review of a new feature or form"],
    ),
    "P3.2": _g(
        "Sensitive personal information is collected only with explicit consent.",
        ["Sensitive categories identified", "Explicit consent captured before collection, and recorded"],
        ["The list of sensitive data collected", "Explicit consent records"],
    ),
    "P4.1": _g(
        "Personal information is used only for the purposes people were told about.",
        [
            "Uses checked against the privacy notice",
            "New uses reviewed (and consent obtained where needed) before they start",
            "Access to personal data limited by role",
        ],
        ["A privacy impact assessment or review of a new use", "Access lists for systems holding personal data"],
    ),
    "P4.2": _g(
        "Personal information is kept only as long as needed.",
        ["Retention periods per type of personal data", "Deletion or anonymisation when the period ends"],
        ["The retention schedule", "Evidence of scheduled deletion"],
    ),
    "P4.3": _g(
        "Personal information is disposed of securely.",
        ["Secure deletion from systems and backups", "Disposal recorded", "Deletion on request where the law gives that right"],
        ["A deletion record", "A handled deletion request"],
    ),
    "P5.1": _g(
        "People can see the personal information held about them.",
        ["A process for access requests: identity checked, answered within the legal time", "Requests logged"],
        ["The access request procedure", "The request log with response times"],
    ),
    "P5.2": _g(
        "People can have their personal information corrected, and are told if a request is refused.",
        ["A process for correction requests", "Corrections passed on to third parties that hold the data", "Refusals explained in writing"],
        ["The correction procedure", "A handled correction request"],
    ),
    "P6.1": _g(
        "Personal information is given to third parties only for the stated purposes and with consent where needed.",
        [
            "A list of third parties that receive personal data and why",
            "Disclosures match the privacy notice",
            "Contracts in place before data is shared",
        ],
        ["The list of recipients (sub-processors)", "A data processing agreement"],
    ),
    "P6.2": _g(
        "Authorised disclosures of personal information are recorded.",
        ["A record of what was disclosed, to whom, when and why"],
        ["The disclosure log"],
    ),
    "P6.3": _g(
        "Unauthorised disclosures (breaches) of personal information are recorded.",
        ["Breaches and suspected breaches logged with what was affected", "Each one investigated"],
        ["The breach register", "An investigation record"],
    ),
    "P6.4": _g(
        "Vendors that handle personal information commit to protecting it.",
        ["Data processing agreements with privacy and security terms", "Vendors' privacy practices reviewed before use and periodically"],
        ["Signed data processing agreements", "A vendor privacy review"],
    ),
    "P6.5": _g(
        "Vendors commit to telling the company about incidents that affect personal information.",
        ["Breach-notification terms in vendor contracts, with a time limit", "A contact and process for receiving such notices"],
        ["The contract clause", "The vendor incident intake process"],
    ),
    "P6.6": _g(
        "People, regulators and others are told about a breach of personal information when required.",
        ["A breach notification procedure with the legal time limits", "Templates and a decision record for each breach"],
        ["The breach notification procedure", "A notification sent, or the decision record that none was required"],
    ),
    "P6.7": _g(
        "On request, people are told what of their personal information was disclosed and to whom.",
        ["The disclosure log can be searched per person", "A process to answer such requests"],
        ["The procedure", "A handled request"],
    ),
    "P7.1": _g(
        "Personal information is kept accurate, complete and current for its purposes.",
        ["Validation when data is collected", "Ways for people to update their own data", "Periodic checks of data quality"],
        ["Validation rules", "The self-service update feature (screenshots)", "A data quality check"],
    ),
    "P8.1": _g(
        "Privacy questions, complaints and disputes are received, handled and tracked, and compliance with privacy commitments is monitored.",
        [
            "A published privacy contact",
            "Complaints logged, answered and resolved within a set time",
            "Periodic review of privacy compliance, with corrective action",
        ],
        ["The privacy contact", "The complaint log", "The latest privacy compliance review"],
    ),
}


def _from(entries: dict[str, tuple[str, list[str], list[str]]]) -> dict[str, Guidance]:
    return {cid: _g(meaning, to_meet, evidence) for cid, (meaning, to_meet, evidence) in entries.items()}


# HIPAA and NIST CSF 2.0 are written from the public texts, in A.C.O.R.N's own words (see each module). Same shape as SOC 2.
HIPAA: dict[str, Guidance] = _from(_hipaa.ENTRIES)
NIST_CSF: dict[str, Guidance] = {**_from(_nist_gi.ENTRIES), **_from(_nist_pr.ENTRIES)}

GUIDANCE: dict[str, dict[str, Guidance]] = {"SOC2": SOC2, "HIPAA": HIPAA, "NIST-CSF": NIST_CSF}


def guidance_for(framework: str, control_id: str) -> Guidance | None:
    """The guidance for one control of a framework, or None when there is none yet."""
    return GUIDANCE.get(framework, {}).get(control_id)
