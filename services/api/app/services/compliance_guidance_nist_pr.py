"""NIST CSF 2.0 Protect, Detect, Respond and Recover guidance (written for A.C.O.R.N in its own words)."""

ENTRIES: dict[str, tuple[str, list[str], list[str]]] = {
    "PR.AA-01": (
        "Every person, service account and device that can reach your systems has its own identity, and those identities are created, changed and removed in a controlled way.",
        [
            "A joiner, mover and leaver process that creates and removes accounts the same day staff start or leave",
            "A central directory or identity provider so accounts are not scattered across tools",
            "An inventory of service accounts and shared accounts, each with a named owner",
            "A regular review that finds and disables dormant accounts and unused devices",
        ],
        [
            "The joiner, mover and leaver procedure",
            "A list of accounts from the directory showing owner and last sign-in",
            "A ticket showing an account removed after someone left",
        ],
    ),
    "PR.AA-02": (
        "Before someone is given an account or credential, you check they are who they say they are, with more care for higher-risk access.",
        [
            "A rule for how new staff and clients prove who they are before an account is issued",
            "A callback or in-person check before resetting a password or changing a multi-factor device",
            "Stronger checks for administrator and finance accounts than for ordinary ones",
            "Records of who approved each new identity",
        ],
        [
            "The identity verification procedure for new accounts and resets",
            "A help desk script showing the verification steps",
            "A sample of onboarding tickets with the check recorded",
        ],
    ),
    "PR.AA-03": (
        "Users, services and devices must prove who they are each time they sign in, using more than a password for anything important.",
        [
            "Multi-factor sign-in turned on for all users, and enforced for email, remote access and admin accounts",
            "Password rules that favor long passphrases and block known breached passwords",
            "Certificates or managed keys, not shared passwords, for services and devices",
            "Conditional access or lockout rules that stop repeated failed sign-ins",
        ],
        [
            "A report showing multi-factor sign-in coverage by user",
            "Screenshots of the password and lockout settings",
            "The list of any accounts excluded from multi-factor with the reason",
        ],
    ),
    "PR.AA-04": (
        "The sign-in tokens and assertions that pass your identity from one system to another are protected so they cannot be stolen, forged or replayed.",
        [
            "Single sign-on over encrypted connections only, with signed assertions or tokens",
            "Short token lifetimes and the ability to revoke sessions when an account is at risk",
            "Verification of the token issuer and audience by every application that accepts it",
            "Signing keys and secrets stored in a vault or managed key service and rotated",
        ],
        [
            "The single sign-on configuration showing signing and token lifetime settings",
            "Screenshot of session revocation in the identity provider",
            "Key rotation record for token signing keys",
        ],
    ),
    "PR.AA-05": (
        "People and services get only the access their job needs, and no one person can complete a sensitive task alone.",
        [
            "Access granted by role and approved by a manager or system owner",
            "Separate everyday accounts and administrator accounts, with admin rights limited and time-bound",
            "Split duties for risky actions such as payments, backups deletion and security setting changes",
            "A recurring access review that removes rights people no longer need",
        ],
        [
            "The role and access matrix",
            "The latest access review sign-off with changes made",
            "A list of administrator accounts with owners",
            "An approval record for a recent privileged access request",
        ],
    ),
    "PR.AA-06": (
        "Offices, server rooms and equipment are physically locked down, and you know who has been in them.",
        [
            "Locked server rooms and network closets with a short list of people allowed in",
            "Badges, keys or door codes issued and returned through a tracked process",
            "A visitor sign-in and escort rule for areas holding equipment or client data",
            "Cameras or door logs reviewed where equipment is kept",
        ],
        [
            "The physical access policy and authorized-person list",
            "A visitor log sample",
            "Door access or key issue records",
            "A photo of the locked server area or rack",
        ],
    ),
    "PR.AT-01": (
        "All staff know how to spot and avoid common security problems and what to do when something looks wrong.",
        [
            "Security awareness training for every new starter and again each year",
            "Phishing simulations with follow-up coaching for people who click",
            "Short reminders when a new scam or threat is going around",
            "A simple way to report a suspicious email or event, known to everyone",
        ],
        [
            "Training completion report by employee",
            "Phishing simulation results over time",
            "The training material or agenda",
        ],
    ),
    "PR.AT-02": (
        "People in roles with extra security duties, such as administrators, developers and executives, get training suited to those duties.",
        [
            "A list of roles that need extra training, such as system administrators and incident handlers",
            "Role-based training on topics such as secure configuration, incident handling and data handling",
            "Training for leadership on their part in risk decisions and incident communication",
            "Completion tracked and refreshed when roles or threats change",
        ],
        [
            "The list of specialized roles and their required training",
            "Certificates or completion records for those staff",
            "Course outlines for role-based sessions",
        ],
    ),
    "PR.DS-01": (
        "Data stored on disks, servers, laptops and cloud services is kept private and unaltered, and stays available when needed.",
        [
            "Full-disk encryption on laptops, desktops and servers, enforced by device management",
            "Encryption turned on for databases, storage buckets and backups",
            "Access to stored data limited to those who need it",
            "A data classification so the most sensitive data gets the strongest protection",
        ],
        [
            "A device management report showing disk encryption status",
            "Screenshots of cloud storage and database encryption settings",
            "The data classification policy",
        ],
    ),
    "PR.DS-02": (
        "Data moving over networks, between systems and to clients is protected from being read or changed on the way.",
        [
            "Encrypted connections (TLS) required for websites, email and APIs",
            "VPN or zero-trust access for remote staff reaching internal systems",
            "Old protocols and weak ciphers turned off",
            "Certificates tracked and renewed before they expire",
        ],
        [
            "A scan result showing the TLS settings of public services",
            "VPN or remote access configuration screenshots",
            "The certificate inventory with expiry dates",
        ],
    ),
    "PR.DS-10": (
        "Data is kept safe even while a program is using it in memory or on screen, not only when stored or sent.",
        [
            "Screen lock and session timeout rules on all devices",
            "Controls that stop copying sensitive data to personal apps, removable drives or unmanaged devices",
            "Endpoint protection that blocks malicious code reading memory or scraping credentials",
            "Sensitive systems run in managed environments, with confidential computing where the risk justifies it",
        ],
        [
            "Device policy screenshots for screen lock and removable media",
            "Data loss prevention or endpoint protection settings",
            "The acceptable use policy covering sensitive data handling",
        ],
    ),
    "PR.DS-11": (
        "Backups of important data are made on a schedule, kept safe from tampering, and proven to restore.",
        [
            "Automatic backups of servers, cloud services and email with a stated retention period",
            "At least one copy kept offline or immutable so ransomware cannot delete it",
            "Backups encrypted and accessible only to a small, named group",
            "Restore tests on a schedule with the results recorded",
        ],
        [
            "Backup job status report covering all protected systems",
            "A completed restore test record with date and outcome",
            "The backup policy showing retention and copy locations",
        ],
    ),
    "PR.PS-01": (
        "Systems are built from an agreed secure setup, and any changes to that setup are tracked rather than made ad hoc.",
        [
            "Standard secure build settings for workstations, servers and network gear",
            "Configuration managed by tools (device management, scripts or templates), not by hand",
            "A change process that records, approves and can undo configuration changes",
            "Checks that flag systems drifting away from the standard",
        ],
        [
            "The configuration baseline documents",
            "A configuration compliance report from device management",
            "A change ticket with approval for a recent change",
        ],
    ),
    "PR.PS-02": (
        "Software is kept up to date, and software that is no longer supported is replaced or removed before it becomes a hole.",
        [
            "Patch management that installs operating system and application updates on a defined timetable",
            "Faster timelines for critical and actively exploited vulnerabilities",
            "A list of software with its support end dates and a plan to replace it",
            "Removal of applications nobody uses",
        ],
        [
            "A patch compliance report across devices",
            "The patching policy with timelines",
            "An end-of-life software list with replacement plans",
        ],
    ),
    "PR.PS-03": (
        "Computers, network gear and other hardware are maintained, replaced when they age out, and wiped safely when retired.",
        [
            "A hardware inventory with purchase dates and warranty or support end dates",
            "A refresh plan that replaces unsupported equipment",
            "Firmware updates applied to firewalls, switches and servers",
            "Secure wiping or destruction of drives, with a certificate, when equipment is disposed of",
        ],
        [
            "The hardware inventory with lifecycle dates",
            "Firmware update records",
            "A disposal or wipe certificate for retired devices",
        ],
    ),
    "PR.PS-04": (
        "Systems record what happens on them, and those records are collected where they can be watched and kept.",
        [
            "Logging turned on for sign-ins, administrator actions, firewalls, email and cloud services",
            "Log collection into a central tool (a log platform or SIEM) with a set retention period",
            "Logs protected so they cannot be quietly edited or deleted",
            "Clocks synchronized across systems so events line up",
        ],
        [
            "A list of log sources feeding the central tool",
            "Screenshot of log retention settings",
            "A sample search showing recent events from several systems",
        ],
    ),
    "PR.PS-05": (
        "Only approved software can be installed and run, and unknown or malicious programs are stopped.",
        [
            "Users without local administrator rights so they cannot install programs freely",
            "Application allow-listing or an approved software list enforced by endpoint protection",
            "Blocking of macros, scripts and downloads from untrusted sources where possible",
            "A request process for adding new software that includes a security check",
        ],
        [
            "The approved software list",
            "Endpoint protection or allow-list policy screenshot",
            "A software request ticket showing review",
        ],
    ),
    "PR.PS-06": (
        "If you build or customize software, you build it securely and measure how well that is working.",
        [
            "Secure coding standards and code review before changes go live",
            "Automated scans of code, dependencies and containers in the build pipeline",
            "Separate development, test and production environments with controlled promotion",
            "Tracking of findings and how quickly they are fixed",
        ],
        [
            "The secure development policy",
            "A build pipeline scan report",
            "A reviewed pull request or change record",
        ],
    ),
    "PR.IR-01": (
        "Your networks and cloud environments are set up so that only the right people and systems can get in or move around.",
        [
            "Firewalls with default-deny rules, reviewed on a schedule",
            "Network segments that keep servers, staff devices, guests and client environments apart",
            "Remote administration limited to approved paths, protected by multi-factor sign-in",
            "Cloud security groups and public exposure checked regularly",
        ],
        [
            "A network diagram showing segments",
            "Firewall rule review record",
            "A scan showing which services are reachable from the internet",
        ],
    ),
    "PR.IR-02": (
        "Equipment is protected from fire, flood, heat, power loss and similar physical hazards.",
        [
            "Equipment kept in rooms with cooling, fire detection and, where suitable, suppression",
            "Battery backup and surge protection for servers and network gear",
            "Placement away from water risks, with environmental sensors and alerts",
            "Cloud or hosting providers chosen with evidence of their own facility protections",
        ],
        [
            "Photos of the server room showing cooling and fire detection",
            "Battery backup test or maintenance record",
            "A hosting provider facility report or certification",
        ],
    ),
    "PR.IR-03": (
        "Systems are designed to keep working, or recover quickly, both on a normal day and when something goes wrong.",
        [
            "Resilience targets for important services, such as how long each may be down",
            "Redundancy for key parts like internet links, firewalls, storage and critical servers",
            "Failover tested for the most important services",
            "Fail-safe behavior that keeps security controls on if a component fails",
        ],
        [
            "A list of important services with their recovery targets",
            "An architecture diagram showing redundancy",
            "A failover test result",
        ],
    ),
    "PR.IR-04": (
        "You keep enough computing, storage, network and licence capacity so services stay available as demand changes.",
        [
            "Monitoring of disk, memory, processor, bandwidth and licence usage",
            "Alerts when usage nears set limits",
            "Capacity reviewed regularly and planned ahead of growth",
            "Protection against traffic floods that could exhaust capacity",
        ],
        [
            "A capacity dashboard or report",
            "An alert rule screenshot for usage thresholds",
            "A capacity review note with decisions made",
        ],
    ),
    "DE.CM-01": (
        "Network traffic and services are watched so unusual or hostile activity is noticed quickly.",
        [
            "Firewall and network device logs collected and reviewed",
            "Intrusion detection or network detection tooling at key points",
            "DNS and web filtering logs watched for known bad destinations",
            "Alerts routed to a person or team who responds",
        ],
        [
            "A list of network sources being monitored",
            "A sample alert and its handling record",
            "Screenshot of detection tool configuration",
        ],
    ),
    "DE.CM-02": (
        "Physical spaces where equipment or data live are watched for signs of unauthorized entry or damage.",
        [
            "Cameras or alarms covering entrances and equipment rooms",
            "Door access logs reviewed, with alerts for after-hours or forced entry",
            "Environmental alerts for water, smoke and temperature",
            "A named person responsible for responding to physical alarms",
        ],
        [
            "Alarm or camera system screenshot or photo",
            "A sample door access log review",
            "A record of an alarm and the response",
        ],
    ),
    "DE.CM-03": (
        "Staff and system account activity is watched for behavior that looks risky, such as odd sign-ins or mass downloads.",
        [
            "Sign-in and account activity monitoring with alerts for impossible travel, new devices and failed attempts",
            "Alerts on admin actions, mailbox rule changes and large data downloads",
            "Monitoring done within a published acceptable use and privacy policy",
            "Someone assigned to review and follow up on these alerts",
        ],
        [
            "A list of user activity alerts that are turned on",
            "A sample alert for risky sign-in with its follow-up",
            "The acceptable use and monitoring policy",
        ],
    ),
    "DE.CM-06": (
        "The activity of outside providers and the services they run for you is watched for signs of trouble.",
        [
            "A list of suppliers with access to your systems or data",
            "Logging of vendor and partner remote access sessions",
            "Review of provider security notices, status pages and service reports",
            "Alerts for unusual activity from supplier accounts",
        ],
        [
            "The supplier list showing level of access",
            "Vendor access log sample",
            "A record of a supplier report or notice that was reviewed",
        ],
    ),
    "DE.CM-09": (
        "Computers, servers, software and the environments they run in are watched for malicious or unexpected activity.",
        [
            "Endpoint detection and response or equivalent protection on every computer and server",
            "Alerts for malware, suspicious processes and changes to important files",
            "Cloud workload and container monitoring where those are used",
            "Protection kept switched on, with alerts if it is disabled",
        ],
        [
            "An endpoint protection coverage report",
            "A sample detection alert and how it was handled",
            "A list of monitored servers and cloud workloads",
        ],
    ),
    "DE.AE-02": (
        "When something suspicious is flagged, someone looks into it to learn what it is and what it is doing.",
        [
            "A triage routine that checks each alert against what normal looks like",
            "Written steps for common alert types, so analysis is consistent",
            "Notes kept on what was found and why an alert was or was not a real problem",
            "A tuned set of detection rules that cuts out noise",
        ],
        [
            "The alert triage procedure",
            "Analysis notes from a recent alert",
            "A summary of alerts reviewed over the past month",
        ],
    ),
    "DE.AE-03": (
        "Information from many sources is brought together so a pattern across systems can be seen.",
        [
            "A central log or security platform that receives data from endpoints, network, email and identity",
            "Correlation rules that link events such as a phishing email, then a new sign-in, then a mailbox change",
            "Common time stamps and account names to make linking possible",
            "Regular review that gaps in sources are closed",
        ],
        [
            "A list of connected data sources",
            "A correlation rule or detection example",
            "A case where several events were linked into one incident",
        ],
    ),
    "DE.AE-04": (
        "When something bad is spotted, you work out how far it reaches and how much it could hurt.",
        [
            "Questions answered for each event, such as which accounts, devices and data are involved",
            "An asset and data inventory that shows what matters most",
            "A simple impact rating scale tied to business effect",
            "The scope and impact written into the incident record",
        ],
        [
            "The impact rating scale",
            "An incident record showing scope and impact notes",
            "The asset inventory used during analysis",
        ],
    ),
    "DE.AE-06": (
        "The people and tools that need to know about a suspicious event are told promptly.",
        [
            "Alerts sent to an on-call person or ticket queue, not just a mailbox no one reads",
            "A contact list for who is told for which type of event",
            "Automatic feeds from detection tools into the ticketing or response platform",
            "Alert delivery tested from time to time",
        ],
        [
            "The alert routing and on-call schedule",
            "A ticket created automatically from an alert",
            "Results of a notification test",
        ],
    ),
    "DE.AE-07": (
        "Outside threat information and local context are used to make sense of what you see.",
        [
            "Threat intelligence feeds or advisories subscribed to and used by detection tools",
            "Indicators such as bad addresses and file hashes checked against your logs",
            "Context about your own business, such as critical systems and usual hours, added to analysis",
            "Someone responsible for reading advisories and acting on those that apply",
        ],
        [
            "A list of intelligence sources in use",
            "An example where an advisory led to a search or rule change",
            "Screenshot of feed integration in the detection tool",
        ],
    ),
    "DE.AE-08": (
        "You have clear rules for when a suspicious event becomes a declared incident, and you apply them.",
        [
            "Written criteria that say what makes an event an incident",
            "A named person or role with authority to declare an incident",
            "A record of the time and reason an incident was declared",
            "Criteria reviewed after incidents and exercises",
        ],
        [
            "The incident definition and declaration criteria",
            "An incident ticket showing declaration time and decision maker",
            "The review notes of the criteria",
        ],
    ),
    "RS.MA-01": (
        "When an incident happens, you follow your written response plan and bring in the outside parties who need to help.",
        [
            "A written incident response plan with roles and steps",
            "Contact details for outside parties such as insurers, legal advisers, forensic help and key suppliers",
            "Contracts or retainers for outside help agreed before it is needed",
            "A tabletop exercise at least yearly to practice the plan",
        ],
        [
            "The incident response plan",
            "The outside contact list",
            "The report from the latest exercise or real incident",
        ],
    ),
    "RS.MA-02": (
        "Reports of possible incidents are checked to confirm whether they are real and need action.",
        [
            "A single place for staff, clients and tools to report possible incidents",
            "A triage step that confirms or dismisses each report and records why",
            "Target times for first response to a report",
            "Feedback to the person who reported it",
        ],
        [
            "The incident reporting procedure",
            "A set of tickets showing triage decisions",
            "A report of response times",
        ],
    ),
    "RS.MA-03": (
        "Incidents are labelled by type and ranked by urgency so the most serious get attention first.",
        [
            "A list of incident categories such as malware, account takeover and data loss",
            "A severity scale based on business effect and data involved",
            "Target response times for each severity level",
            "Priority reviewed again as more is learned",
        ],
        [
            "The category and severity definitions",
            "A recent incident showing category and priority assigned",
            "The response time targets by severity",
        ],
    ),
    "RS.MA-04": (
        "Incidents that are bigger than first thought are passed to more senior or specialist people when needed.",
        [
            "Escalation steps that say who is called and when, by severity",
            "An on-call rota with a backup for every level",
            "Rules for telling management, clients and legal advisers",
            "A record of each escalation with time and reason",
        ],
        [
            "The escalation matrix",
            "The on-call schedule",
            "An incident ticket showing an escalation",
        ],
    ),
    "RS.MA-05": (
        "You decide when it is time to start recovering systems, using clear criteria.",
        [
            "Criteria for starting recovery, such as the threat being contained and evidence being captured",
            "A named decision maker who approves the start of recovery",
            "A check that recovery will not destroy evidence or restore the attacker's access",
            "The decision and its reason written down",
        ],
        [
            "The recovery start criteria in the response plan",
            "A record of a recovery go-ahead decision",
            "An incident timeline showing when recovery began",
        ],
    ),
    "RS.AN-03": (
        "After or during an incident you work out what happened, how it started and why it was possible.",
        [
            "An investigation routine that builds a timeline of events",
            "Access to logs, endpoint data and email records needed to trace the cause",
            "Root cause identified and written down, not just the symptom",
            "Lessons fed back into fixes and detection rules",
        ],
        [
            "An incident report with timeline and root cause",
            "A list of fixes that came from the investigation",
            "The investigation checklist or template",
        ],
    ),
    "RS.AN-06": (
        "What investigators do during an incident is written down, and those records are kept trustworthy.",
        [
            "A case log that records every action, who did it and when",
            "Case notes stored in a system with restricted access and edit history",
            "Rules for handling evidence so its source can be shown",
            "Records kept for the period set by policy or contract",
        ],
        [
            "A sample case log",
            "Access settings for the case record store",
            "The evidence handling procedure",
        ],
    ),
    "RS.AN-07": (
        "Data from an incident, such as logs, files and device images, is collected carefully so it can be trusted.",
        [
            "Steps for capturing logs, memory, disk images and email copies before systems are cleaned",
            "File hashes and a chain of custody record for important evidence",
            "Evidence stored read-only in a secured location",
            "Time stamps recorded for when and by whom data was collected",
        ],
        [
            "The evidence collection procedure",
            "A chain of custody form for a collected item",
            "A record of file hashes taken at collection",
        ],
    ),
    "RS.AN-08": (
        "You estimate how big an incident is, and check that estimate as facts come in.",
        [
            "A way to count affected users, devices, systems and records",
            "Checks of the estimate against logs and other evidence",
            "Estimates updated as the investigation continues",
            "The final size recorded for reporting and for legal notification decisions",
        ],
        [
            "An incident report with the affected counts",
            "Notes showing how the estimate was checked",
            "The impact estimate used for a notification decision",
        ],
    ),
    "RS.CO-02": (
        "The right people inside and outside the company are told when an incident happens.",
        [
            "A list of who must be told, such as management, affected clients, insurers, regulators and law enforcement",
            "Notification deadlines from contracts and laws written into the plan",
            "Message templates approved ahead of time",
            "A record of who was told, when, and by whom",
        ],
        [
            "The notification matrix with deadlines",
            "Draft notice templates",
            "A log of notifications from a real incident or exercise",
        ],
    ),
    "RS.CO-03": (
        "Useful information about an incident is shared with the right internal and outside groups during the response.",
        [
            "Agreements on what may be shared and with whom",
            "Regular status updates to leaders and affected clients during an incident",
            "Sharing of threat details with trusted groups such as industry sharing groups or the provider's security team",
            "Sensitive details limited to those who need them",
        ],
        [
            "A sharing and communication plan",
            "An example status update sent during an incident",
            "Membership or contact with a threat sharing group",
        ],
    ),
    "RS.MI-01": (
        "You stop an incident from spreading while you work on it.",
        [
            "Ready-made containment actions such as isolating a device, disabling an account and blocking an address",
            "Endpoint protection able to isolate a computer from the network remotely",
            "Authority for the on-call team to take these actions without waiting",
            "Containment steps and times recorded",
        ],
        [
            "The containment playbooks",
            "Screenshot of the device isolation feature",
            "An incident record showing containment actions and times",
        ],
    ),
    "RS.MI-02": (
        "You remove the cause of the incident, such as malware, rogue accounts or the weakness used to get in.",
        [
            "Steps to remove malware, persistence methods and attacker accounts",
            "Passwords, keys and tokens reset where they may have been exposed",
            "The entry weakness patched or closed",
            "A check that nothing of the attacker remains before recovery finishes",
        ],
        [
            "The eradication checklist",
            "An incident record showing credentials reset and fixes applied",
            "A follow-up scan showing the system is clean",
        ],
    ),
    "RC.RP-01": (
        "Once recovery starts, you carry out the recovery part of your incident plan.",
        [
            "A written recovery plan with steps, owners and order of work",
            "A recovery lead who tracks progress against the plan",
            "Recovery tools and backups available and tested ahead of time",
            "Progress recorded in the incident ticket",
        ],
        [
            "The recovery section of the incident response plan",
            "A recovery task list from a real incident or exercise",
            "A record of the recovery lead's decisions",
        ],
    ),
    "RC.RP-02": (
        "Recovery actions are chosen, sized, ranked and carried out in a sensible order.",
        [
            "A ranked list of systems and services to restore first, based on business need",
            "Recovery time and data loss targets for each important service",
            "A choice between restoring from backup, rebuilding or repairing, with the reason noted",
            "Approval of the plan before big restores begin",
        ],
        [
            "The recovery priority list with targets",
            "A recovery plan showing the approach chosen for an incident",
            "Approval record for the recovery steps",
        ],
    ),
    "RC.RP-03": (
        "Backups and other restore material are checked to be clean and intact before you restore from them.",
        [
            "Backup integrity checks such as checksums and test mounts",
            "Malware scanning of backups before restoring them",
            "Choosing a restore point from before the attacker was active",
            "Backups kept in a place the attacker could not reach or change",
        ],
        [
            "A backup verification report",
            "A malware scan result for a backup used in recovery",
            "Notes on how the restore point was chosen",
        ],
    ),
    "RC.RP-04": (
        "After an incident, you decide what normal looks like again, balancing key business functions and risk.",
        [
            "A review of which services the business needs most to run",
            "Updated security settings and monitoring added where the incident showed gaps",
            "Agreement from business owners on the new baseline",
            "Changes recorded in the risk register",
        ],
        [
            "A post-incident review with the agreed baseline",
            "Changes made to controls after the incident",
            "The updated risk register entry",
        ],
    ),
    "RC.RP-05": (
        "Restored systems are checked to be sound, brought back into service, and confirmed to be running normally.",
        [
            "Checks of restored data, applications and security tools before returning to use",
            "A test that users and key functions work correctly",
            "Extra monitoring of restored systems for a period after recovery",
            "Sign-off from the system owner that normal service is back",
        ],
        [
            "A restoration checklist with results",
            "System owner sign-off",
            "Monitoring results from the period after recovery",
        ],
    ),
    "RC.RP-06": (
        "You formally close the incident recovery when set criteria are met, and finish the paperwork.",
        [
            "Written criteria for when recovery is over",
            "A named person who declares recovery complete",
            "A final incident report and a lessons learned meeting",
            "Records filed and follow-up actions assigned with owners and dates",
        ],
        [
            "The recovery completion criteria",
            "The final incident report",
            "The lessons learned notes with action items",
        ],
    ),
    "RC.CO-03": (
        "People affected by an incident are kept up to date on how recovery is going.",
        [
            "A communication plan with who gets updates and how often",
            "A named person who writes and sends updates",
            "Updates that cover what is back, what is not, and what happens next",
            "Copies of updates kept with the incident record",
        ],
        [
            "The communication plan",
            "Copies of updates sent to staff and clients",
            "A log of update times for an incident",
        ],
    ),
    "RC.CO-04": (
        "Anything shared with the public about recovery uses approved channels and wording.",
        [
            "A named spokesperson and an approval step for public statements",
            "Pre-approved holding statements and templates",
            "Review by legal and leadership before release",
            "Public channels such as the website and social accounts under controlled access",
        ],
        [
            "The public communication policy",
            "Approved statement templates",
            "A public update with its approval record",
        ],
    ),
}
