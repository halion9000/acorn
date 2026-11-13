"""HIPAA Security Rule guidance (written for A.C.O.R.N in its own words)."""

ENTRIES: dict[str, tuple[str, list[str], list[str]]] = {
    "164.308(a)(1)": (
        "The practice must run an ongoing process to find, reduce and watch the risks to the electronic patient information it holds (a standard with four parts below).",
        [
            "A written security management policy that points to the four parts: risk analysis, risk management, sanctions and activity review",
            "An owner who keeps that process running through the year",
            "A calendar of the recurring reviews so none of them is skipped",
        ],
        [
            "The security management policy with its approval date",
            "The review calendar or task list showing the last completed round",
        ],
    ),
    "164.308(a)(1)(ii)(A)": (
        "Risk analysis (required): the practice must look honestly at where patient data lives and what could go wrong with it, and write down what it found.",
        [
            "Required: an inventory of systems, devices, cloud services and paper-to-digital flows that touch patient data",
            "A list of threats and weak points for each, with a rating of how likely and how harmful",
            "A repeat of the analysis at least yearly and after big changes such as a new system or office move",
        ],
        [
            "The latest risk analysis report with its date and author",
            "The asset and data-flow inventory it was based on",
            "Notes or tickets showing the previous round was updated",
        ],
    ),
    "164.308(a)(1)(ii)(B)": (
        "Risk management (required): the risks found in the analysis must be cut down to a level the practice has decided it can accept, with the work tracked.",
        [
            "Required: a risk register or action plan with an owner and a target date for every item",
            "Budget or time set aside to actually fix the higher-rated items",
            "A recorded decision for any risk that is accepted instead of fixed",
        ],
        [
            "The risk register or remediation plan",
            "Tickets or change records showing fixes completed",
            "Sign-off notes for accepted risks",
        ],
    ),
    "164.308(a)(1)(ii)(C)": (
        "Sanction policy (required): staff who break the practice's security rules face consequences that are written down and applied fairly.",
        [
            "Required: a written policy listing the kinds of violations and the range of responses",
            "Staff told about the policy when hired and again at training",
            "A record of any action taken, kept in a restricted file",
        ],
        [
            "The sanction policy with its approval date",
            "Signed staff acknowledgements for a sample of employees",
            "An example of a recorded violation and the response, with names removed",
        ],
    ),
    "164.308(a)(1)(ii)(D)": (
        "Information system activity review (required): someone must regularly look at the logs and reports of systems holding patient data to spot misuse.",
        [
            "Required: a defined list of what is reviewed, such as sign-in logs, access reports and security alerts",
            "A set schedule for the review and a named person who does it",
            "A way to raise anything odd as an incident",
        ],
        [
            "The review procedure or checklist",
            "Dated review sign-offs or tickets for recent weeks or months",
            "A sample report or log extract that was reviewed",
        ],
    ),
    "164.308(a)(2)": (
        "One named person must be in charge of security for the practice or for the services provided to it, so that nothing falls between the cracks.",
        [
            "A named security official, with the role written into a job description or appointment letter",
            "A backup person who can act when the official is away",
            "Staff and clients who know who to contact about security",
        ],
        [
            "The appointment letter or job description naming the official",
            "An org chart or contact page showing the role",
        ],
    ),
    "164.308(a)(3)": (
        "Only staff who need to see patient data for their job should be able to reach it, and the practice needs rules for who that is (a standard with three parts below).",
        [
            "A written workforce security policy tying data access to job roles",
            "Procedures for the three parts below: supervision, clearance and termination",
            "Managers who know they must request or remove access when roles change",
        ],
        [
            "The workforce security policy",
            "A role-to-access matrix for the main systems",
        ],
    ),
    "164.308(a)(3)(ii)(A)": (
        "Authorization and/or supervision (addressable): people who work with patient data, or in places where it is kept, should be approved to do so or watched by someone who is.",
        [
            "Addressable: a rule that says who may approve access and who supervises people without full approval, such as interns and visiting technicians",
            "Visitors and contractors escorted or logged when near systems with patient data",
            "A written note of the reason if the practice picks another approach",
        ],
        [
            "The procedure for approving and supervising workers",
            "A visitor or contractor log from a recent period",
            "A sample approval record for a new staff member",
        ],
    ),
    "164.308(a)(3)(ii)(B)": (
        "Workforce clearance procedure (addressable): before someone is given access to patient data, the practice checks that the access is appropriate for them.",
        [
            "Addressable: a pre-access check that fits the role, such as identity checks, references or background screening where the law allows",
            "A manager sign-off that the access requested matches the job",
            "Documented reasons if the practice decides a lighter check is enough",
        ],
        [
            "The clearance or onboarding checklist",
            "A completed checklist for a recent hire with details removed",
            "The access request approval for the same person",
        ],
    ),
    "164.308(a)(3)(ii)(C)": (
        "Termination procedures (addressable): when someone leaves or changes jobs, their access to patient data must be cut or adjusted quickly.",
        [
            "Addressable: an offboarding checklist covering accounts, email, remote access, keys, badges and devices",
            "A target time for removal, such as the same day, and an owner who confirms it",
            "A periodic check that no leavers still have working accounts",
        ],
        [
            "The offboarding checklist",
            "Completed checklists or tickets for recent departures",
            "A user list compared against the staff roster showing no stale accounts",
        ],
    ),
    "164.308(a)(4)": (
        "The practice needs written rules for deciding who gets access to patient data, at what level, and how that access is granted and changed (a standard with three parts below).",
        [
            "A written access management policy based on need to know",
            "Procedures for the parts below: authorization, setup and later changes",
            "A named approver for access to each system holding patient data",
        ],
        [
            "The access management policy",
            "A current list of systems with their approvers",
        ],
    ),
    "164.308(a)(4)(ii)(A)": (
        "Isolating health care clearinghouse functions (required, but only for a clearinghouse that is part of a larger organization): that part must keep its patient data away from the rest of the organization.",
        [
            "Required where it applies: separate systems, networks or access groups for the clearinghouse work",
            "Rules that stop the parent organization from reaching clearinghouse data without permission",
            "A written statement that the control does not apply if the practice is not part of a clearinghouse",
        ],
        [
            "A network or access diagram showing the separation",
            "The applicability statement, or the policy covering the isolation",
        ],
    ),
    "164.308(a)(4)(ii)(B)": (
        "Access authorization (addressable): the practice should have a clear way for someone in charge to approve who may use a given system, program or record set.",
        [
            "Addressable: an access request form or ticket that must be approved by the data or system owner",
            "Standard access levels per job role so approvals are consistent",
            "Records of who approved what and when",
        ],
        [
            "The access request procedure",
            "A sample of approved access requests",
            "The role-based access level list",
        ],
    ),
    "164.308(a)(4)(ii)(C)": (
        "Access establishment and modification (addressable): the practice should have a defined way to set up, review and change a person's access as their needs change.",
        [
            "Addressable: a documented process for creating accounts and changing permissions after a role move",
            "A regular review where managers confirm each person still needs the access they have",
            "Changes logged so they can be traced back to a request",
        ],
        [
            "The account setup and change procedure",
            "The latest access review with manager sign-off",
            "Change tickets showing a permission added or removed",
        ],
    ),
    "164.308(a)(5)": (
        "Everyone who works with patient data, including managers, must be trained on security so they can protect it in daily work (a standard with four parts below).",
        [
            "A security awareness program that covers all staff and new hires",
            "A record of who was trained and when",
            "Training content that matches the practice's own policies and tools",
        ],
        [
            "The training plan or policy",
            "Attendance or completion records for all staff",
        ],
    ),
    "164.308(a)(5)(ii)(A)": (
        "Security reminders (addressable): staff should get regular nudges about security between formal trainings, such as new scams or policy changes.",
        [
            "Addressable: a routine channel for reminders, such as monthly emails, posters or short messages",
            "Extra reminders when a new threat or a change in procedure comes up",
            "A record of what was sent and to whom",
        ],
        [
            "Copies of recent reminders with dates",
            "The schedule or plan for sending them",
        ],
    ),
    "164.308(a)(5)(ii)(B)": (
        "Protection from malicious software (addressable): the practice should have ways to detect and stop viruses, ransomware and similar threats, and teach staff to spot them.",
        [
            "Addressable: endpoint protection on all computers and servers, kept up to date and monitored",
            "Email filtering for harmful attachments and links",
            "Staff taught to report suspicious messages and a place to report them",
        ],
        [
            "A console report showing protection installed and healthy on every device",
            "Email filter settings or a screenshot of them",
            "A record of a recent detected threat and how it was handled",
        ],
    ),
    "164.308(a)(5)(ii)(C)": (
        "Log-in monitoring (addressable): the practice should watch for failed or odd sign-ins to systems with patient data and report what it finds.",
        [
            "Addressable: sign-in logging turned on for all systems with patient data, including cloud services",
            "Alerts for repeated failures, sign-ins from unusual places and sign-ins at odd hours",
            "A step for someone to look at the alerts and act on them",
        ],
        [
            "A screenshot of sign-in logging and alert settings",
            "A sample alert and the follow-up ticket",
            "Review notes covering sign-in activity",
        ],
    ),
    "164.308(a)(5)(ii)(D)": (
        "Password management (addressable): the practice should have rules for creating, changing and protecting passwords, and staff who follow them.",
        [
            "Addressable: a password policy covering length, reuse and what to do after a suspected leak",
            "A password manager or similar tool so staff do not write passwords down or share them",
            "Multi-factor sign-in for email, remote access and systems with patient data",
        ],
        [
            "The password policy",
            "A screenshot of password and multi-factor settings in the main identity system",
            "A report showing multi-factor coverage across user accounts",
        ],
    ),
    "164.308(a)(6)": (
        "The practice must be ready to spot, handle and learn from security incidents that affect patient data (a standard with one part below).",
        [
            "A written incident response policy with a named lead",
            "A way for staff to report a problem quickly and without blame",
            "Contact details for the people who must be told, such as management, the IT provider and counsel",
        ],
        [
            "The incident response policy or plan",
            "The staff reporting instructions or contact page",
        ],
    ),
    "164.308(a)(6)(ii)": (
        "Response and reporting (required): when an incident happens, the practice must act to limit the harm, and keep a written account of what happened and what was done.",
        [
            "Required: a step-by-step response procedure from first report to recovery and lessons learned",
            "An incident log recording each event, its outcome and any breach notification decision",
            "A review after serious incidents to improve the plan",
        ],
        [
            "The incident response procedure",
            "The incident log or tickets from the last year",
            "A written post-incident review for one real or practice event",
        ],
    ),
    "164.308(a)(7)": (
        "The practice must have a plan to keep patient care going and get patient data back if systems fail, are attacked or are destroyed (a standard with five parts below).",
        [
            "A contingency plan document that brings together backup, recovery and emergency operation",
            "A named person for each part of the plan and a contact list",
            "A review of the plan after major changes",
        ],
        [
            "The contingency plan with its approval date",
            "The contact list and role assignments for the plan",
        ],
    ),
    "164.308(a)(7)(ii)(A)": (
        "Data backup plan (required): exact copies of patient data must be made regularly so nothing is lost if the original goes missing.",
        [
            "Required: automated backups of every system holding patient data, with a defined frequency",
            "Backup copies kept somewhere that an attack or fire on the main site cannot reach",
            "Alerts when a backup fails and someone who responds to them",
        ],
        [
            "The backup policy listing what is backed up and how often",
            "A backup job report showing recent successful runs",
            "A screenshot of the offsite or immutable storage settings",
        ],
    ),
    "164.308(a)(7)(ii)(B)": (
        "Disaster recovery plan (required): the practice must know how to restore lost patient data and systems after a disaster, in what order and by whom.",
        [
            "Required: written recovery steps for each important system, with the order of restoration",
            "Target times for getting each system back, agreed with the practice's management",
            "Access to the plan and to backup credentials even when the main systems are down",
        ],
        [
            "The disaster recovery plan",
            "A recovery time target table for key systems",
            "Proof that a copy of the plan is stored outside the main systems",
        ],
    ),
    "164.308(a)(7)(ii)(C)": (
        "Emergency mode operation plan (required): the practice must know how to keep protecting patient data while running in a reduced way during an emergency.",
        [
            "Required: written steps for working during an outage, such as paper forms or backup systems, with security still in force",
            "Rules for who may authorize emergency procedures",
            "Steps to move paper records back into normal systems afterward",
        ],
        [
            "The emergency mode operation procedure",
            "Downtime forms or templates kept ready for use",
            "Notes from a drill or walk-through of the procedure",
        ],
    ),
    "164.308(a)(7)(ii)(D)": (
        "Testing and revision procedures (addressable): the contingency plan should be tried out from time to time and fixed where the test shows gaps.",
        [
            "Addressable: a yearly test such as a table-top exercise or a real restore from backup",
            "Notes of what went wrong and a plan updated to match",
            "A record of who took part and when it took place",
        ],
        [
            "A test report or exercise notes with the date",
            "A restore test log showing data recovered successfully",
            "The plan revision history showing changes after testing",
        ],
    ),
    "164.308(a)(7)(ii)(E)": (
        "Applications and data criticality analysis (addressable): the practice should rank its systems and data by how badly care would suffer without them, so recovery goes in the right order.",
        [
            "Addressable: a list of applications and data sets with a rating for how critical each one is",
            "Recovery priority and target times tied to those ratings",
            "A review of the ranking whenever systems are added or retired",
        ],
        [
            "The criticality ranking or business impact table",
            "The system inventory it was built from",
        ],
    ),
    "164.308(a)(8)": (
        "The practice must periodically check whether its security measures still work and still fit the rules, especially after business or technology changes.",
        [
            "A scheduled evaluation at least yearly, and after major changes such as a new system or a move",
            "A technical element such as a vulnerability scan or penetration test along with the policy review",
            "A written result with follow-up actions assigned to owners",
        ],
        [
            "The latest evaluation report with its date",
            "Vulnerability scan or test results",
            "The action list that came from the evaluation",
        ],
    ),
    "164.308(b)(1)": (
        "Before a vendor or partner handles patient data for the practice, the practice must get written assurance that they will protect it (a business associate arrangement).",
        [
            "A list of every vendor that creates, stores or sends patient data for the practice",
            "A signed business associate agreement with each of them before data is shared",
            "A check that the vendor has reasonable security before onboarding and now and then afterward",
        ],
        [
            "The vendor list marked with which ones are business associates",
            "Signed agreements for a sample of vendors",
            "Vendor security review records or questionnaires",
        ],
    ),
    "164.308(b)(3)": (
        "Written contract or other arrangement (required): the assurance from a business associate must be put in writing, usually as a signed agreement.",
        [
            "Required: a written agreement with each business associate covering how it will protect the data and report problems",
            "A standard agreement template that the practice keeps current",
            "A tracker showing agreement status and renewal dates",
        ],
        [
            "The agreement template",
            "Signed copies for current vendors",
            "The tracker or register showing none is missing",
        ],
    ),
    "164.310(a)(1)": (
        "The practice must limit physical access to the buildings and rooms that hold its computer systems, while still letting authorized people get in (a standard with four parts below).",
        [
            "A facility access policy that covers offices, server rooms, wiring closets and storage areas",
            "Locks, badges or keys managed by a named person",
            "Procedures for the four parts below",
        ],
        [
            "The facility access policy",
            "A key or badge holder list",
        ],
    ),
    "164.310(a)(2)(i)": (
        "Contingency operations (addressable): the practice should have a plan for letting the right people into the facility to carry out recovery work during an emergency.",
        [
            "Addressable: a written way to give emergency access to recovery staff and the IT provider when normal arrangements fail",
            "A backup key or code held by a trusted person",
            "Rules for how emergency entry is recorded afterward",
        ],
        [
            "The emergency facility access procedure",
            "A record of who holds backup keys or codes",
        ],
    ),
    "164.310(a)(2)(ii)": (
        "Facility security plan (addressable): the practice should have a plan to protect its building and equipment from break-ins, tampering and theft.",
        [
            "Addressable: locks, alarms or cameras suited to the site, and locked rooms for servers and network gear",
            "Rules for visitors, deliveries and after-hours access",
            "A review of the plan after any incident or layout change",
        ],
        [
            "The facility security plan",
            "Photos or notes of locks, alarms or cameras in place",
            "A visitor log sample",
        ],
    ),
    "164.310(a)(2)(iii)": (
        "Access control and validation procedures (addressable): the practice should check people's identity and role before letting them into areas with systems or patient data.",
        [
            "Addressable: a rule that visitors are identified, signed in and escorted in sensitive areas",
            "Access levels for rooms matched to job roles",
            "Regular review of who holds keys or badges for restricted areas",
        ],
        [
            "The visitor and access validation procedure",
            "Visitor sign-in sheets from a recent period",
            "The latest review of key or badge holders",
        ],
    ),
    "164.310(a)(2)(iv)": (
        "Maintenance records (addressable): repairs and changes to the physical parts of the building that guard security, such as doors, locks and walls, should be written down.",
        [
            "Addressable: a log of repairs and changes to security-related physical features",
            "A record of who did the work and when, including outside contractors",
            "A step to check security still works after the repair",
        ],
        [
            "The maintenance log",
            "An invoice or work order for a recent lock or door repair",
        ],
    ),
    "164.310(b)": (
        "Workstation use (required): the practice must say how computers that touch patient data may be used and what sort of surroundings they belong in.",
        [
            "Required: a written policy covering permitted tasks, screen privacy and where workstations may be placed",
            "Rules for remote work, home offices and personal devices",
            "Staff acknowledgement of the policy",
        ],
        [
            "The workstation use policy",
            "Signed staff acknowledgements for a sample of employees",
            "The remote work or personal device policy",
        ],
    ),
    "164.310(c)": (
        "Workstation security (required): the practice must physically protect computers that can reach patient data from use by unauthorized people.",
        [
            "Required: screens that face away from public view or have privacy filters",
            "Cable locks, locked rooms or lockable cabinets for equipment in open areas",
            "Staff habit or rule to lock the screen when leaving a desk",
        ],
        [
            "Photos of workstation placement in public-facing areas",
            "Screen lock settings exported from device management",
        ],
    ),
    "164.310(d)(1)": (
        "The practice must control how hardware and media that hold patient data, such as laptops, drives and tapes, move in, out and around the organization (a standard with four parts below).",
        [
            "A device and media control policy",
            "A list of what is covered, including laptops, phones, USB drives and backup media",
            "Procedures for the four parts below: disposal, re-use, tracking and backup",
        ],
        [
            "The device and media control policy",
            "The list of covered device types",
        ],
    ),
    "164.310(d)(2)(i)": (
        "Disposal (required): when hardware or media that held patient data is thrown out or recycled, the data on it must be made unreadable first.",
        [
            "Required: a disposal procedure using wiping to a recognized standard or physical destruction",
            "A certificate or record from any outside shredding or recycling firm",
            "A step to cover paper printouts and old backup media as well",
        ],
        [
            "The disposal procedure",
            "Destruction or wipe certificates for recent items",
            "A disposal log with dates and asset identifiers",
        ],
    ),
    "164.310(d)(2)(ii)": (
        "Media re-use (required): before a computer or drive that held patient data is handed to someone else, its data must be removed first.",
        [
            "Required: a rule that devices are securely wiped or reset before they are reissued",
            "A checklist signed off by the person who performed the wipe",
            "Verification that the wipe worked, such as a status report from the tool",
        ],
        [
            "The re-use or reissue procedure",
            "A completed wipe checklist for a recent device",
            "A wipe tool report or log",
        ],
    ),
    "164.310(d)(2)(iii)": (
        "Accountability (addressable): the practice should keep track of where devices and media with patient data are and who has them.",
        [
            "Addressable: an asset register that shows owner, location and status of each device",
            "A sign-out process for portable drives and loaner laptops",
            "A regular check of the register against what is physically there",
        ],
        [
            "The asset register export",
            "A sign-out log for portable devices",
            "The latest reconciliation notes",
        ],
    ),
    "164.310(d)(2)(iv)": (
        "Data backup and storage (addressable): before moving equipment that holds patient data, the practice should make a safe copy of that data so it is not lost in the move.",
        [
            "Addressable: a step in the move or repair process to save a verified copy first",
            "Rules for where that copy is kept and who can read it",
            "Removal of the temporary copy when it is no longer needed",
        ],
        [
            "The equipment move or repair checklist including the backup step",
            "A record of a backup taken before a recent move or repair",
        ],
    ),
    "164.312(a)(1)": (
        "Technical controls must make sure only approved people and programs can reach patient data in electronic systems (a standard with four parts below).",
        [
            "Role-based access in every system that holds patient data",
            "Central sign-in, such as a single identity system, wherever possible",
            "Procedures for the four parts below",
        ],
        [
            "A screenshot or export of roles and groups in the main system",
            "The technical access control policy",
        ],
    ),
    "164.312(a)(2)(i)": (
        "Unique user identification (required): every person who uses a system with patient data needs their own login so actions can be traced back to them.",
        [
            "Required: individual accounts for all staff and contractors, with no shared logins",
            "A rule against sharing credentials, backed by regular checks for generic accounts",
            "Service accounts kept separate, documented and owned by a named person",
        ],
        [
            "A user list showing individual accounts only",
            "The policy banning shared logins",
            "A list of service accounts with their owners",
        ],
    ),
    "164.312(a)(2)(ii)": (
        "Emergency access procedure (required): the practice must know how to get at patient data during an emergency when normal sign-in is not possible.",
        [
            "Required: a documented break-glass method, such as sealed admin credentials held by a named person",
            "Rules for who may use it and how use is logged and reviewed afterward",
            "Credentials changed after each use",
        ],
        [
            "The emergency access procedure",
            "A record showing the credentials are stored securely",
            "Log or review notes of the last time it was used or tested",
        ],
    ),
    "164.312(a)(2)(iii)": (
        "Automatic logoff (addressable): sessions on systems with patient data should end or lock after a period of inactivity.",
        [
            "Addressable: a screen lock or session timeout on workstations, servers and cloud applications",
            "Timeout length chosen to suit the work area, shorter in public spaces",
            "Settings enforced centrally so users cannot turn them off",
        ],
        [
            "A group policy or device management screenshot showing the timeout",
            "Application session timeout settings",
        ],
    ),
    "164.312(a)(2)(iv)": (
        "Encryption and decryption (addressable): patient data stored on devices and servers should be scrambled so that a lost or stolen device does not expose it.",
        [
            "Addressable: full-disk encryption on laptops, desktops and servers that hold patient data",
            "Encryption on backups and in cloud storage",
            "Safe storage of recovery keys, with a written reason if encryption is not used somewhere",
        ],
        [
            "An encryption status report across all devices",
            "Backup or cloud storage encryption settings",
            "The documented decision for any item left unencrypted",
        ],
    ),
    "164.312(b)": (
        "Audit controls (required): systems that hold or use patient data must record activity so the practice can look back and see who did what.",
        [
            "Required: logging turned on for access to patient data in key systems and for admin actions",
            "Logs protected from change and kept for a set period",
            "A procedure that makes sure someone actually reviews them",
        ],
        [
            "Screenshots of audit logging settings",
            "A sample log extract showing user, action and time",
            "The log retention setting or policy",
        ],
    ),
    "164.312(c)(1)": (
        "The practice must protect patient data from being changed or destroyed in ways that are not authorized (a standard with one part below).",
        [
            "Write access limited to the people who need to change records",
            "Backups and version history so wrong changes can be undone",
            "Checks that look for unexpected changes in important data",
        ],
        [
            "Permission settings for key records",
            "Backup or version history settings",
        ],
    ),
    "164.312(c)(2)": (
        "Mechanism to authenticate electronic protected health information (addressable): the practice should have a way to confirm that stored patient data has not been altered or damaged.",
        [
            "Addressable: checksums, file integrity monitoring or database integrity features on important data",
            "Alerts when protected files change unexpectedly",
            "Documented reasoning if another method is used instead",
        ],
        [
            "Integrity monitoring configuration or tool report",
            "A sample alert and its follow-up",
        ],
    ),
    "164.312(d)": (
        "Person or entity authentication (required): systems must check that anyone asking for patient data is really who they claim to be.",
        [
            "Required: passwords or stronger proof for every user and every system-to-system connection",
            "Multi-factor sign-in for remote access, email and admin accounts",
            "Verification steps for help desk password resets so attackers cannot talk their way in",
        ],
        [
            "A multi-factor enrollment report",
            "Authentication settings from the identity system",
            "The help desk identity verification procedure",
        ],
    ),
    "164.312(e)(1)": (
        "Patient data sent over a network must be guarded against being read or changed on the way (a standard with two parts below).",
        [
            "A transmission security policy that covers email, web, file transfer and remote access",
            "Approved tools for sending patient data, with unapproved ones blocked or discouraged",
            "Procedures for the two parts below",
        ],
        [
            "The transmission security policy",
            "A list of approved tools and methods for sending patient data",
        ],
    ),
    "164.312(e)(2)(i)": (
        "Integrity controls (addressable): the practice should have ways to notice if patient data was altered while moving across a network.",
        [
            "Addressable: secure protocols such as TLS or signed messages that detect tampering",
            "Checks on file transfers to confirm what arrived matches what was sent",
            "A written reason if the practice relies on another approach",
        ],
        [
            "Configuration showing secure protocols in use",
            "A scan or test result confirming strong connections",
        ],
    ),
    "164.312(e)(2)(ii)": (
        "Encryption (addressable): patient data sent over open or shared networks, including email and the internet, should be encrypted.",
        [
            "Addressable: encrypted connections for websites, remote access and file transfer, with old protocols turned off",
            "Email encryption for messages that carry patient data outside the practice",
            "VPN or similar protection for staff working away from the office",
        ],
        [
            "A TLS scan of public sites and portals",
            "Email encryption settings or policy rules",
            "VPN or remote access configuration screenshots",
        ],
    ),
    "164.314(a)(1)": (
        "When the practice relies on a vendor or partner to handle patient data, the contract must meet the Security Rule's expectations (a standard with one part below).",
        [
            "Business associate agreements in place before any patient data is shared",
            "A process to catch new vendors that need an agreement",
            "A procedure for what to do when a vendor does not agree to the terms",
        ],
        [
            "The vendor register with agreement status",
            "Signed agreements for a sample of vendors",
        ],
    ),
    "164.314(a)(2)": (
        "Business associate contract requirements (required): each agreement must oblige the vendor to protect the data, to pass the same duties to its own subcontractors and to report security incidents.",
        [
            "Required: agreement terms covering safeguards, subcontractor flow-down, incident reporting and return or destruction of data",
            "Language letting the practice end the contract if the vendor breaks the terms",
            "A legal or compliance review of the template whenever the rules change",
        ],
        [
            "The agreement template with the required terms highlighted",
            "A signed agreement showing those terms",
            "Review notes from the last template update",
        ],
    ),
    "164.314(b)(1)": (
        "Requirements for group health plans: a group health plan must make sure the plan sponsor will protect electronic patient data it receives, and this applies only to those plans.",
        [
            "A plan document that holds the sponsor to the security duties",
            "A statement that the control does not apply if the practice is not a group health plan",
            "A sponsor who understands and agrees to the obligations",
        ],
        [
            "The plan document amendment or the not-applicable statement",
            "The sponsor's written agreement",
        ],
    ),
    "164.314(b)(2)": (
        "Group health plan implementation specifications (required for group health plans only): the plan documents must require the sponsor to protect the data, keep plan data separate, bind agents and report incidents.",
        [
            "Required where it applies: plan terms that cover safeguards, separation of plan data, agents and reporting of incidents",
            "A way for the sponsor to report security incidents to the plan",
            "A statement of non-applicability for entities that are not group health plans",
        ],
        [
            "The plan terms covering these points",
            "The not-applicable statement, if relevant",
            "A sample of the sponsor incident reporting procedure",
        ],
    ),
    "164.316(a)": (
        "Policies and procedures: the practice must write down and follow the rules that carry out the Security Rule, and keep them in step with its real environment.",
        [
            "A written policy set that covers each part of the Security Rule that applies to the practice",
            "Policies that are reasonable for its size and systems, and that staff can actually follow",
            "An owner who updates them when systems or laws change",
        ],
        [
            "The policy library with an index",
            "Version history showing policies are kept current",
            "Staff acknowledgement records",
        ],
    ),
    "164.316(b)(1)": (
        "Documentation: the policies, plans and records that show what the practice decided and did about security must be kept in written form, on paper or electronically.",
        [
            "A single place where policies, risk analyses, training records and incident records are stored",
            "A record of any action, activity or assessment the rule asks to be documented",
            "Access controls on the document store itself",
        ],
        [
            "A screenshot of the document repository structure",
            "A sample of dated records such as a training log or review sign-off",
        ],
    ),
    "164.316(b)(2)(i)": (
        "Time limit (required): security documents must be kept for six years from the date they were created or last in effect, whichever is later.",
        [
            "Required: a retention rule that keeps policies and records for at least six years",
            "Old versions archived rather than overwritten",
            "A step that stops deletion of covered records before the period ends",
        ],
        [
            "The retention policy stating the period",
            "A listing of archived older policy versions",
        ],
    ),
    "164.316(b)(2)(ii)": (
        "Availability (required): the people who carry out the procedures must be able to read the documents that apply to them.",
        [
            "Required: policies placed where staff can reach them, such as an intranet or shared drive",
            "Access rights so each role can open the documents it needs",
            "Copies available during an outage, for example a printed or offline set",
        ],
        [
            "A screenshot of the policy location with access settings",
            "Evidence of an offline or printed copy for emergencies",
        ],
    ),
    "164.316(b)(2)(iii)": (
        "Updates (required): the practice must review its security documents regularly and change them when the environment or operations change.",
        [
            "Required: a review schedule, at least yearly, with a named owner",
            "A trigger to update documents after incidents, new systems or changes in the rules",
            "A change log showing what changed and who approved it",
        ],
        [
            "The review schedule or calendar",
            "Policy version history with dated revisions",
            "Approval records for the latest update",
        ],
    ),
}
