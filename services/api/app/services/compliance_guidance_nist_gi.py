"""NIST CSF 2.0 Govern and Identify guidance (written for A.C.O.R.N in its own words)."""

ENTRIES: dict[str, tuple[str, list[str], list[str]]] = {
    # ---- GV.OC Organizational context
    "GV.OC-01": (
        "The company knows what it exists to do and lets that purpose decide how much security effort goes where.",
        [
            "A short written statement of the mission and the services the business must keep running",
            "Security priorities that are tied to that mission, so protecting the most important services comes first",
            "A review of the statement when the business changes, such as a new service line or a large client",
        ],
        [
            "The mission and service statement with its approval date",
            "A security plan or roadmap that points back to those services",
        ],
    ),
    "GV.OC-02": (
        "The company knows who has a stake in its security (clients, staff, owners, regulators, partners) and what each of them expects.",
        [
            "A list of stakeholder groups with what each one expects from the company on security",
            "A named owner for each important relationship, such as the account manager for a key client",
            "A way to collect expectations again when contracts renew or the business changes",
        ],
        [
            "The stakeholder list with expectations",
            "Notes from a client or owner meeting where security expectations were discussed",
            "Security sections of client contracts or onboarding questionnaires",
        ],
    ),
    "GV.OC-03": (
        "The company has found the laws, regulations and contract terms that apply to it and has a way of keeping up with them.",
        [
            "A register of the laws, industry rules and contract security clauses that apply (privacy, breach notice, client terms)",
            "A named person who owns the register and checks it at least once a year",
            "A link from each requirement to the policy or control that meets it",
            "A process to review new client contracts for security and privacy terms before signing",
        ],
        [
            "The legal and contractual requirements register",
            "A record of the last review of that register",
            "A contract review checklist or a signed-off example",
        ],
    ),
    "GV.OC-04": (
        "The company knows which of its services its clients and others depend on most, and how much interruption each can survive.",
        [
            "A list of critical services (remote monitoring, help desk, backup, email security) and who relies on each",
            "An agreed target for how fast each critical service must be back after an outage",
            "Those targets used when planning backups, redundancy and staffing",
        ],
        [
            "The critical services list with recovery targets",
            "A business impact analysis or a short summary of one",
            "Service level terms from a client agreement that match those targets",
        ],
    ),
    "GV.OC-05": (
        "The company knows which outside services and providers it depends on to deliver its own work, and what happens if one fails.",
        [
            "A list of the tools, cloud platforms and providers the business cannot work without",
            "A note for each one on what breaks if it goes down and what the fallback is",
            "The dependency list reviewed at least once a year",
        ],
        [
            "The dependency list with fallback notes",
            "A dependency map or diagram for the main services",
        ],
    ),
    # ---- GV.RM Risk management strategy
    "GV.RM-01": (
        "Leaders have said what the company wants its risk work to achieve, and the people affected agree.",
        [
            "A written risk management objective statement approved by leadership",
            "Objectives that can be checked, such as keeping critical risks below an agreed count",
            "A review with owners or key stakeholders when the objectives are set or changed",
        ],
        [
            "The approved risk management objectives",
            "Meeting minutes or a sign-off showing leadership agreed",
        ],
    ),
    "GV.RM-02": (
        "Leadership has said how much risk the company is willing to accept, and staff know where those limits are.",
        [
            "A risk appetite statement in plain words, such as no tolerance for unprotected client data",
            "Numeric or rated limits that tell staff when a risk must be escalated",
            "The statement shared with managers and used when approving exceptions",
        ],
        [
            "The risk appetite and tolerance statement with its approval date",
            "A note or email showing how it was shared with staff",
            "An exception or acceptance record that cites the limits",
        ],
    ),
    "GV.RM-03": (
        "Security risks are handled together with the other business risks, not in a separate silo.",
        [
            "Security risks recorded in the same risk register as financial, legal and operational risks",
            "Security risk results included in regular management or owner meetings",
            "One method of rating risks used across all types of risk",
        ],
        [
            "The company risk register showing security entries",
            "Agenda or minutes of a management meeting that covered security risk",
        ],
    ),
    "GV.RM-04": (
        "The company's strategy says what choices exist for dealing with a risk (reduce it, avoid it, transfer it or accept it) and who may pick which.",
        [
            "A written list of the response options and when each is appropriate",
            "Rules on who can approve accepting a risk and up to what size",
            "Cyber insurance or contract terms considered as a way to transfer risk",
        ],
        [
            "The risk response guidance or risk management procedure",
            "A sample risk record showing the chosen response and who approved it",
            "The current cyber insurance policy summary",
        ],
    ),
    "GV.RM-05": (
        "There are clear paths for passing security risk information up to leaders, across teams and out to clients and suppliers.",
        [
            "A defined escalation path with names and thresholds for when a risk goes to leadership",
            "A regular risk report to management, at least quarterly",
            "A way to tell affected clients and suppliers about risks that concern them",
        ],
        [
            "The escalation procedure or contact list",
            "A recent risk report sent to leadership",
            "A client or supplier notice about a risk or incident",
        ],
    ),
    "GV.RM-06": (
        "The company rates and ranks risks in one consistent way so that two people looking at the same risk reach about the same score.",
        [
            "A written method with defined scales for how likely and how damaging a risk is",
            "A scoring matrix or formula that turns those scales into a priority",
            "Every register entry scored with the method and re-scored when things change",
        ],
        [
            "The risk assessment methodology document",
            "The risk register showing scores and priority order",
        ],
    ),
    "GV.RM-07": (
        "The company also looks at the upside of taking chances, such as new services or tools, and weighs it against the security cost.",
        [
            "A step in project or service planning that asks for both the benefit and the security risk",
            "Opportunities written down next to threats when strategy is discussed",
            "A decision record that shows how the benefit was weighed against the risk",
        ],
        [
            "A planning template with a risk and opportunity section",
            "A decision record or proposal for a new service that covers both sides",
        ],
    ),
    # ---- GV.RR Roles, responsibilities and authorities
    "GV.RR-01": (
        "Leaders own the security risk personally and set an example, so staff take security seriously.",
        [
            "A named executive or owner who is accountable for cybersecurity risk",
            "Leadership following the same security rules as everyone else, such as multi-factor sign-in",
            "Security discussed at leadership meetings and mentioned in company messages to staff",
        ],
        [
            "A statement or policy signed by the accountable leader",
            "Leadership meeting minutes that include security",
            "A staff message from leadership about security expectations",
        ],
    ),
    "GV.RR-02": (
        "Everyone's security duties and the authority to act on them are written down and understood.",
        [
            "A responsibility chart that names who owns each security area (access, backup, incident response, vendor review)",
            "Security duties in job descriptions and in client contracts where the company acts for clients",
            "Authority stated plainly, such as who may shut down a system or approve an exception",
            "Roles confirmed with the people who hold them at least once a year",
        ],
        [
            "The roles and responsibilities chart",
            "Job descriptions that mention security duties",
            "A record of the last annual confirmation",
        ],
    ),
    "GV.RR-03": (
        "The company gives security enough people, money and tools for the level of risk it has chosen to manage.",
        [
            "A security budget or a named line in the company budget",
            "Staffing or contracted help sized to the work, including coverage when someone is away",
            "A review of whether resources fit the risk, at least yearly",
        ],
        [
            "The security budget or spending summary",
            "A staffing plan or contract with an outside security provider",
        ],
    ),
    "GV.RR-04": (
        "Security is part of how the company hires, manages and lets go of people.",
        [
            "Background checks for roles with access to systems or client data, where the law allows",
            "Security responsibilities and confidentiality terms in employment agreements",
            "Security training during onboarding and a checklist that removes all access when someone leaves",
            "Security expectations included in performance discussions for roles that have access",
        ],
        [
            "The hiring checklist showing the screening step",
            "A signed confidentiality agreement or acknowledgement (redacted)",
            "A completed leaver checklist for a recent departure",
        ],
    ),
    # ---- GV.PO Policy
    "GV.PO-01": (
        "The company has a written security policy that follows from its risk decisions, and everyone has been told about it.",
        [
            "A written cybersecurity policy that reflects the risk appetite and the legal and contract duties",
            "Approval by leadership and a named owner",
            "A record that staff have read and accepted it, plus a place where they can find it again",
        ],
        [
            "The approved policy with version and date",
            "Staff acknowledgement records",
            "The intranet page or message that announced the policy",
        ],
    ),
    "GV.PO-02": (
        "The policy is checked on a schedule and whenever something major changes, and staff hear about the changes.",
        [
            "A yearly review date for each policy",
            "A trigger list for earlier reviews, such as a serious incident, a new law or a major system change",
            "A version history and a message to staff when the policy changes",
        ],
        [
            "Policy version history showing the last review",
            "The notice sent to staff about the latest update",
        ],
    ),
    # ---- GV.OV Oversight
    "GV.OV-01": (
        "Leaders look at how the security strategy is doing and change direction based on what they find.",
        [
            "A regular management review of security results, at least once a year",
            "Results (incidents, audit findings, metrics) given to leaders before the meeting",
            "Decisions and actions from the review written down and followed up",
        ],
        [
            "Management review minutes with decisions",
            "The results pack or slides shown at the review",
            "An action list with status from the review",
        ],
    ),
    "GV.OV-02": (
        "The strategy is checked against current requirements and risks, and adjusted when it no longer covers them.",
        [
            "A yearly comparison of the strategy with the requirements register and the risk register",
            "Gaps noted and assigned to an owner with a due date",
            "An update to the strategy when a new risk or requirement appears",
        ],
        [
            "A gap review or coverage comparison document",
            "The updated strategy with a change note",
        ],
    ),
    "GV.OV-03": (
        "The company measures how well its security risk work is actually performing and acts on the results.",
        [
            "A small set of measures, such as time to fix critical vulnerabilities, training completion and open high risks",
            "Measures collected on a schedule and reported to leaders",
            "Targets for each measure and follow-up when a target is missed",
        ],
        [
            "A metrics report or dashboard export covering several months",
            "A record of an action taken because a measure missed its target",
        ],
    ),
    # ---- GV.SC Supply chain risk management
    "GV.SC-01": (
        "The company has an agreed programme for managing the security risk that comes from suppliers, with a policy that says how.",
        [
            "A written supplier risk management policy approved by leadership",
            "A named owner for the programme",
            "Defined steps for choosing, onboarding, monitoring and ending a supplier",
        ],
        [
            "The supplier risk management policy or procedure",
            "A document naming the programme owner",
        ],
    ),
    "GV.SC-02": (
        "The security duties of suppliers, clients and partners are spelled out, and each side knows what it must do for the others.",
        [
            "A shared responsibility description for each key supplier and for each service offered to clients",
            "Contacts on both sides for security matters and incidents",
            "These roles included in contracts or service descriptions",
        ],
        [
            "A shared responsibility matrix for a key supplier or client service",
            "Contract sections that set out security duties",
            "A contact list for supplier and client security matters",
        ],
    ),
    "GV.SC-03": (
        "Supplier risk is part of the company's normal security and business risk work, not handled on the side.",
        [
            "Supplier risks recorded in the main risk register",
            "Supplier risk results included in management risk reports",
            "The same scoring method used for supplier and internal risks",
        ],
        [
            "The risk register with supplier entries",
            "A management report that includes supplier risk",
        ],
    ),
    "GV.SC-04": (
        "The company has a full list of its suppliers and has ranked them by how much damage a failure or breach at each could do.",
        [
            "A supplier inventory with what each one provides and what data or access it has",
            "A criticality rating for each supplier using clear criteria",
            "The list reviewed at least once a year and when a new supplier is added",
        ],
        [
            "The supplier inventory with criticality ratings",
            "The criteria used to rate suppliers",
        ],
    ),
    "GV.SC-05": (
        "Security requirements for suppliers are decided in advance and put into the agreements with them.",
        [
            "Standard security terms for supplier contracts, such as breach notice time, data handling and audit rights",
            "Stronger terms for the suppliers rated as critical",
            "A check by a named person that contracts include these terms before signature",
        ],
        [
            "The standard supplier security clauses",
            "A signed supplier agreement showing those clauses",
            "A contract review checklist for suppliers",
        ],
    ),
    "GV.SC-06": (
        "The company does its homework on a supplier before signing, so risks are known before the relationship starts.",
        [
            "A due diligence step before onboarding, such as a security questionnaire or review of a SOC 2 or ISO report",
            "Approval from a named person before a supplier gets access to data or systems",
            "Findings from the review recorded, with any gaps either fixed or accepted",
        ],
        [
            "A completed supplier questionnaire or report review",
            "An onboarding approval record",
            "A note of accepted gaps with the approver",
        ],
    ),
    "GV.SC-07": (
        "The company understands the risk each supplier brings, writes it down, ranks it and keeps watching it over time.",
        [
            "A risk entry for each important supplier in the register",
            "Reassessment on a schedule, yearly for critical suppliers",
            "Monitoring of supplier news, breach notices and certificate or report expiry",
            "Follow-up on issues found, tracked to closure",
        ],
        [
            "Supplier risk assessments with dates",
            "A supplier review log showing reassessments",
            "A record of a supplier issue and how it was followed up",
        ],
    ),
    "GV.SC-08": (
        "Suppliers that matter are brought into the company's planning for incidents, response and recovery.",
        [
            "Incident contacts and notice times agreed with each critical supplier",
            "Critical suppliers listed in the incident response and recovery plans",
            "Joint exercises or walk-throughs with key suppliers where practical",
        ],
        [
            "The incident response plan section that covers suppliers",
            "Supplier emergency contact list",
            "Notes from a joint exercise or call with a supplier",
        ],
    ),
    "GV.SC-09": (
        "Supplier security checks are part of the company's regular practice, and the results are watched throughout the life of the relationship.",
        [
            "Supplier checks scheduled in the same calendar as other security activities",
            "Results of supplier checks reported to the programme owner",
            "Changes in a supplier's service or ownership reviewed for new risk",
        ],
        [
            "The security activity calendar showing supplier reviews",
            "A report or summary of supplier review results",
        ],
    ),
    "GV.SC-10": (
        "The supplier plans cover what happens after the contract ends or changes, including getting data back and cutting access.",
        [
            "Contract terms for returning or deleting company and client data at the end of service",
            "An exit checklist that removes supplier accounts, keys and network access",
            "A plan for moving to another supplier if a critical one fails or leaves",
        ],
        [
            "Contract clauses on data return and deletion",
            "A completed exit checklist for a past supplier",
            "A transition or exit plan for a critical supplier",
        ],
    ),
    # ---- ID.AM Asset management
    "ID.AM-01": (
        "The company keeps an up to date list of the computers, servers, network gear and other devices it manages.",
        [
            "A single inventory of devices with owner, location and type",
            "An automatic source such as the remote monitoring tool feeding that inventory",
            "A check at least quarterly that finds missing or unknown devices and fixes the list",
        ],
        [
            "An export of the hardware inventory with dates",
            "A record of the last reconciliation and what it found",
        ],
    ),
    "ID.AM-02": (
        "The company keeps a list of the software, cloud services and systems it uses and runs.",
        [
            "An inventory of installed software, subscriptions and cloud applications with an owner for each",
            "Approval needed before new software or services are added",
            "Regular checks for unapproved software or shadow services",
        ],
        [
            "The software and services inventory",
            "A report of detected software compared against the approved list",
            "An approval record for a new tool",
        ],
    ),
    "ID.AM-03": (
        "The company has diagrams or records of which connections and data flows are allowed on its network and between its systems.",
        [
            "Current network diagrams for the office, cloud and any client connections",
            "A data flow diagram for the systems that handle sensitive or client data",
            "Firewall rules that match the allowed flows, and diagrams updated after network changes",
        ],
        [
            "Network and data flow diagrams with a revision date",
            "A firewall rule review record",
        ],
    ),
    "ID.AM-04": (
        "The company keeps a list of the services that suppliers provide to it and what each one touches.",
        [
            "A register of supplier services with what data, systems or access each has",
            "An owner on the company side for each supplier service",
            "The register compared with accounts payable or subscription records to find missing ones",
        ],
        [
            "The supplier services register",
            "A reconciliation against the invoice or subscription list",
        ],
    ),
    "ID.AM-05": (
        "Assets are ranked by how important they are, so the most valuable and most critical get the most protection first.",
        [
            "A classification scheme with a few clear levels (for example public, internal, confidential)",
            "Each asset given a criticality rating based on the impact of losing it",
            "Protection and recovery priorities that follow those ratings",
        ],
        [
            "The classification scheme or asset policy",
            "The asset inventory showing criticality ratings",
            "A recovery priority list that follows the ratings",
        ],
    ),
    "ID.AM-07": (
        "The company knows what data it holds, where it is kept and who is responsible for it.",
        [
            "A data inventory listing types of data, where each is stored and who owns it",
            "Labels or notes saying how sensitive each data type is and how long it is kept",
            "The inventory reviewed at least once a year or when a new system is added",
        ],
        [
            "The data inventory or data map",
            "A retention schedule",
        ],
    ),
    "ID.AM-08": (
        "Assets are looked after from the day they are bought or built until they are safely retired.",
        [
            "A standard process for setting up new devices and systems securely before use",
            "Patching, support-end tracking and replacement planning for ageing assets",
            "A disposal procedure that wipes data and records how each device was retired",
            "Asset status in the inventory kept current (in use, in repair, retired)",
        ],
        [
            "A build or onboarding checklist for a new device",
            "A report of assets nearing end of support",
            "Disposal or data wipe certificates",
        ],
    ),
    # ---- ID.RA Risk assessment
    "ID.RA-01": (
        "The company finds weaknesses in its systems, checks that they are real and keeps a record of them.",
        [
            "Regular vulnerability scans of servers, workstations and internet-facing systems",
            "Findings checked to remove false alarms and rated by seriousness",
            "Every confirmed finding recorded with an owner and tracked until fixed",
        ],
        [
            "A recent vulnerability scan report",
            "The tracking list of findings with status",
            "The scan schedule or scanner configuration screenshot",
        ],
    ),
    "ID.RA-02": (
        "The company receives warnings about new threats from outside sources, such as vendors, government alerts and peer groups.",
        [
            "Subscriptions to alerts from sources relevant to the company's tools (vendor advisories, national cyber agency, industry groups)",
            "A named person who reads the alerts and decides what applies",
            "A path from relevant alerts into patching or detection work",
        ],
        [
            "A list of the intelligence sources and subscriptions",
            "An example alert and the action it led to",
        ],
    ),
    "ID.RA-03": (
        "The company writes down the threats it faces, from inside and outside, that could harm its business or its clients.",
        [
            "A threat list covering outside attackers, insider mistakes or misuse, and supplier failures",
            "Threats related to the company's real situation, such as attacks on managed service providers",
            "The list reviewed at least yearly and after a major incident",
        ],
        [
            "The threat register or threat assessment document",
            "A record of the last review",
        ],
    ),
    "ID.RA-04": (
        "The company thinks through how bad it would be, and how likely, if a threat used a weakness it has.",
        [
            "For each key risk a note on the likely business impact (downtime, data loss, cost, client trust)",
            "A likelihood estimate that considers the known threats and the weaknesses found",
            "Scenarios for the most serious cases, such as ransomware on a client or a stolen admin account",
        ],
        [
            "Risk assessment entries showing impact and likelihood",
            "A written scenario analysis for a major risk",
        ],
    ),
    "ID.RA-05": (
        "Threats, weaknesses, likelihood and impact are combined into a clear picture of how much risk the company carries before any controls help.",
        [
            "A risk assessment that combines threat, weakness, likelihood and impact for each risk",
            "A score for the risk before controls and another after controls",
            "The results used to decide priorities and presented to leadership",
        ],
        [
            "The risk assessment report with inherent and residual scores",
            "Leadership presentation or minutes covering the results",
        ],
    ),
    "ID.RA-06": (
        "For each risk the company decides what to do about it, plans the work, tracks it and tells the people involved.",
        [
            "A response chosen for each significant risk (fix, avoid, transfer or accept) and recorded",
            "A treatment plan with an owner, due date and budget where needed",
            "Progress tracked and reported, with any accepted risk signed off by the right person",
        ],
        [
            "The risk treatment plan",
            "Risk register entries showing the response and status",
            "A signed risk acceptance record",
        ],
    ),
    "ID.RA-07": (
        "Changes and exceptions to normal rules are reviewed for risk before they happen, then recorded and followed.",
        [
            "A change process that asks for a risk and rollback check before any significant change",
            "An exception process with approval, an end date and compensating protections",
            "A log of changes and exceptions that is reviewed on a schedule",
        ],
        [
            "The change management procedure",
            "A sample change ticket showing risk review and approval",
            "The exception register with expiry dates",
        ],
    ),
    "ID.RA-08": (
        "The company has a way to receive reports of security flaws from outsiders, assess them and respond.",
        [
            "A public security contact (an email address or a security.txt page) where reports can be sent",
            "A procedure to acknowledge, assess and fix reported issues within set times",
            "A process for passing on flaws found in supplier products and for telling affected clients",
        ],
        [
            "The vulnerability disclosure policy or security contact page",
            "A log of reports received and how each was handled",
        ],
    ),
    "ID.RA-09": (
        "The company checks that hardware and software are genuine and have not been tampered with before it buys or installs them.",
        [
            "Buying only from authorised resellers and distributors",
            "Checking signatures, hashes or vendor publishing channels for software before installing",
            "Inspecting hardware for signs of tampering and recording serial numbers on receipt",
        ],
        [
            "The approved supplier or reseller list",
            "A procurement or receiving checklist with the integrity checks",
            "A record of a software signature or hash check",
        ],
    ),
    "ID.RA-10": (
        "Critical suppliers are assessed for security risk before the company commits to buying from them.",
        [
            "A pre-purchase security review required for suppliers rated as critical",
            "Review of independent assurance such as a SOC 2 report, ISO certificate or penetration test summary",
            "A go or no-go decision recorded, with conditions for any gaps",
        ],
        [
            "A completed pre-purchase assessment for a critical supplier",
            "A copy of the assurance report reviewed",
            "The approval record for the purchase",
        ],
    ),
    # ---- ID.IM Improvement
    "ID.IM-01": (
        "The company looks at the results of its audits, assessments and reviews and turns them into actual improvements.",
        [
            "A yearly programme of evaluations such as internal reviews, external audits and client assessments",
            "Findings logged in one improvement list with an owner and due date",
            "Leadership review of open improvements until each is closed",
        ],
        [
            "An audit or assessment report with findings",
            "The improvement tracker showing owners and status",
        ],
    ),
    "ID.IM-02": (
        "Lessons from security tests and practice exercises, including ones run with suppliers, lead to changes.",
        [
            "Regular security tests such as vulnerability scans, penetration tests and phishing simulations",
            "At least one exercise a year, such as an incident tabletop or a restore test, with suppliers involved where they matter",
            "A written list of lessons from each test or exercise, assigned and tracked",
        ],
        [
            "A penetration test or exercise report",
            "Tabletop exercise notes with the lessons learned",
            "Improvement tickets raised from the results",
        ],
    ),
    "ID.IM-03": (
        "Everyday operations, such as handling tickets, incidents and changes, are used as a source of ideas for doing security better.",
        [
            "Reviews after incidents and near misses that ask what should change",
            "A regular look at trends in tickets, alerts and failed changes for repeated causes",
            "Improvements from these reviews recorded and carried out",
        ],
        [
            "A post-incident review report",
            "A trend report from tickets or alerts",
            "The improvement tracker showing items from operations",
        ],
    ),
    "ID.IM-04": (
        "The company has written plans for incidents and other security events, has shared them with the people who need them and keeps them current.",
        [
            "An incident response plan with roles, contacts, steps and client notification rules",
            "Related plans such as business continuity and disaster recovery that point to each other",
            "Plans shared with staff and key suppliers, and reviewed at least yearly and after each real incident",
            "Copies of the plans kept where they can be reached when systems are down",
        ],
        [
            "The incident response plan with version and review date",
            "Business continuity and disaster recovery plans",
            "A record of distribution or training on the plans",
        ],
    ),
}
