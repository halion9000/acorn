# Items waiting on Hal (updated 2026-11-18, evening)

97 items wait on you. 3 are open on my side (last sheet of the spreadsheet). Reply to any item in the text box under it on Settings > Upcoming improvements; I read the replies at the start of each session.

## Action for you (9)

### Move Huntress agents to the organization that matches their NinjaOne client  `huntress-moves`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** About 141 machines are filed in a different Huntress organization than the client NinjaOne files them under. The Huntress API does not move agents (tested on BHRC-FM-01).
- **What it affects:** Huntress organizations and therefore Billing sync counts for Huntress and SAT lines.
- **What I need from you:** Move the agents by hand in the Huntress console from the list I sent (141 machines; 22 have no target organization mapped yet, mostly the 21 Texas Subs machines). Tell me the target organization for the 22.
- **My recommendation:** Nothing for me to build until the 22 targets are known.

### Test Deploy NinjaOne on SCHKNOWCROSS  `ninja-deploy-test`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** Deploy NinjaOne (install the NinjaOne agent from A.C.O.R.N on a machine). The install now runs detached (CORE bc25a2c).
- **What it affects:** Remote install on a real machine (SCHKNOWCROSS).
- **What I need from you:** Press Deploy NinjaOne on SCHKNOWCROSS and tell me what the machine printed. (The live list shows this item marked completed by you; confirm it worked.)
- **My recommendation:** If it worked, nothing more is needed.

### Check sign-in after the cookie change: sign in, sign out, and open Live graph  `a15-live-check`
- **Area:** Platform  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Check sign-in after the cookie change: sign in, reload, sign out. In the browser developer tools (Application) there should be no aisoc.responder.accessToken in local storage and two cookies (aisoc_access, aisoc_refresh).
- **What it affects:** Everyone's sign-in, Microsoft sign-in and the Live graph page.
- **What I need from you:** Try it and tell me what you see.
- **My recommendation:** -

### Qdrant server upgrade (6A39)  `qdrant-upgrade`
- **Area:** Platform  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Upgrade the Qdrant vector database server (item 6A39), after the Sunday 15 Nov snapshot.
- **What it affects:** Leafy and the agents' memory search while it is down.
- **What I need from you:** Pick the time window and approve the upgrade; the snapshot that was due is the safety net.
- **My recommendation:** A Sunday evening after a fresh snapshot.

### Mobile: push notification for a critical alert  `r7-af-39`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Mobile: push notification for a critical alert.
- **What it affects:** Needs a mobile app or web push; depends on the mobile plan.
- **What I need from you:** Decide with r7-ai-36 (the mobile plan), and provide an Apple or Google developer account if an app is wanted.
- **My recommendation:** Web push first.

### Deploy NinjaOne to a Mac: try the package path on a test Mac  `r7-cf-03`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Deploy NinjaOne to a Mac: try the package path on a test Mac.
- **What it affects:** Mac installs of the NinjaOne agent from A.C.O.R.N.
- **What I need from you:** Provide a test Mac and press Deploy, tell me what happened.
- **My recommendation:** -

### Test the Cloudflare canary with a real honeytoken visit from outside  `r7-cf-38`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Test the Cloudflare canary with a real honeytoken visit from outside (a decoy link that should raise an alert).
- **What it affects:** Confirms the canary alert reaches A.C.O.R.N.
- **What I need from you:** Visit the honeytoken address from outside the network and tell me what alert appears.
- **My recommendation:** -

### Install CORE on a clean Windows machine from the installer and note what breaks  `r7-ci-37`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Install CORE on a clean Windows machine from the installer and note what breaks.
- **What it affects:** Confirms a new colleague or a rebuilt VM could install CORE.
- **What I need from you:** Provide a clean Windows machine (or VM) and run the installer, or give me access to do it.
- **My recommendation:** Use a throwaway Azure VM.

### Rotate the CORE feed token and update both sides  `r7-ci-36`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Rotate the CORE feed token (the secret in the address CORE posts to) and update both sides.
- **What it affects:** Briefly stops CORE reporting to A.C.O.R.N until both sides hold the new token. A leaked token lets anyone post as CORE.
- **What I need from you:** Choose a time, and generate or approve the new token (I must not see or print it).
- **My recommendation:** Do it in a quiet hour; I script the change on both sides.

## Check by you (3)

### SaaS billing sync (from Rewst saas-billing): approve license-count differences and push them to HaloPSA  `rw-billing-sync`
- **Area:** Billing  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Billing sync approvals: approving a line makes CORE set the client's recurring invoice in HaloPSA to the counted quantity.
- **What it affects:** Real invoices in HaloPSA; not verified live.
- **What I need from you:** Give someone the Billing role and watch the first approval in Halo (the quantity, and that the other lines stayed).
- **My recommendation:** Also decide how to handle the NW - ThreatMate zeros (see huntress-family).

### SimpleSat: customer satisfaction in CORE and A.C.O.R.N, with reviews on each person  `simplesat-connector`
- **Area:** Metrics  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** SimpleSat customer satisfaction connector in CORE and A.C.O.R.N (CORE reads responses, A.C.O.R.N shows them on Metrics and on each person).
- **What it affects:** Metrics and people pages; built from SimpleSat's published file, not yet read against the live account.
- **What I need from you:** Confirm the daily read works and send the SimpleSat logo in a new message (images sent mid-turn are not saved).
- **My recommendation:** -

### Customer-facing dashboard (from Rewst End User Dashboard): summary, labor hours, customer satisfaction per client  `rw-customer-dashboard`
- **Area:** Reports  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Customer-facing dashboard: the client sign-in (client_viewer role plus authenticator app) and /client-portal showing a company's tickets, hours and satisfaction.
- **What it affects:** What a client sees about themselves; it has not been verified live.
- **What I need from you:** Create one client sign-in for a client linked to HaloPSA, sign in, set up the authenticator app and check the numbers match Metrics > Client summary for that client.
- **My recommendation:** -

## Review by you (3)

### Read the six policy templates and say what to change  `policy-wording-review`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Six policy templates: Information Security, Acceptable Use, Access Control, Incident Response, Vendor Management, Backup and Disaster Recovery (Compliance > Policies > Start a policy from a template).
- **What it affects:** The wording every client policy starts from.
- **What I need from you:** Read them and tell me what to change.
- **My recommendation:** Not urgent; clients will not see Compliance for a while.

### Review the mobile app plan and say what to keep  `r7-ai-36`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Review the mobile app plan and say what to keep.
- **What it affects:** Whether a mobile app is built and what it does (push for critical alerts, approvals).
- **What I need from you:** Read the plan (docs) and tell me what to keep or drop.
- **My recommendation:** -

### Sales and Finance > Profitability and Net income: client profit by month from Halo, typed or QuickBooks costs, and the finance workbook's other sheets  `rw-profitability`
- **Area:** Sales and Finance  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Profitability and Net income with their tabs. Now built: Revenue to net income, New clients, By industry, Hours, Ranking, Client summary, P&L, QBO Profitability, Historical client revenue, QBO Travel, Hardware COGS, Inputs, Settings > Finance, add-on and support software by license counts.
- **What it affects:** Finance numbers you read and decide on.
- **What I need from you:** Look at the live tabs against the workbook and tell me what is off. Also: choose the counts for each software vendor (Settings > Finance > Software costs), set the 10 agents still on the default $65 rate, and answer the Onboarding question.
- **My recommendation:** -

## Approval (1)

### Approve the weekly VM snapshot role command  `r7-cf-39`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Approve the weekly VM snapshot role command (lets the deployment identity create weekly snapshots of the VMs).
- **What it affects:** Azure permissions and cost of snapshots.
- **What I need from you:** Approve the role assignment command.
- **My recommendation:** Approve.

## Go-ahead (1)

### Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6)  `acorn-rename`
- **Area:** Platform  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6 of docs/RENAME_AUDIT_2026-11-15.md change names other things depend on: folders, package names, container names, URLs).
- **What it affects:** Almost everything: builds, deploy scripts, the VM, links. Needs a window when you are away.
- **What I need from you:** Your go-ahead, one step at a time, and tell me when you are away.
- **My recommendation:** Do it in one planned weekend window.

## Access and decision (1)

### Google Workspace BEC: full mailbox scan  `google-bec-scan`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A full Google Workspace mailbox scan for business email compromise. ThreatMate cannot read mailboxes and the light Google check is on hold.
- **What it affects:** Client Google Workspace mailboxes: reads mail, so a privacy and consent matter.
- **What I need from you:** Grant a service account domain-wide delegation with Gmail read scope (or Google Vault export) per client, and say which clients first. Without it nothing can be built.
- **My recommendation:** Start with one friendly client to prove it.

## Question (18)

### NinjaOne warranty dates on devices  `ninja-warranty`
- **Area:** Devices  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** NinjaOne warranty dates on devices. Devices show the warranty end date when NinjaOne's device list carries one, and the maker's own warranty page for Dell and Lenovo from the serial number. Whether NinjaOne's device list really carries a warranty date is not confirmed.
- **What it affects:** Warranty end dates on devices; needs maker API keys.
- **What I need from you:** Checked against the live device records 2026-11-18: NinjaOne devices carry a link to the maker's warranty lookup (warranty_lookup_url) but NO warranty end date, so the date cannot come from NinjaOne. The maker route needs each maker's API: Dell (TechDirect) and Lenovo require an API key or registration. Question for Hal: do you want me to use them (you register and give me a key for Dell and for Lenovo), or leave the link as it is on the device page?


### Net income: an Onboarding section (the workbook's Onboarding tab)  `finance-onboarding-tab`
- **Area:** Finance  |  **Added:** 2026-11-18  |  **Status:** new
- **What it is:** The workbook's Onboarding tab is a list of time entries on onboarding projects (773 rows from April 2026: user, role, customer, project, phase, task, effort, tracked time, billable, category, notes, approved).
- **What it affects:** A possible new Net income section: onboarding hours and labor cost per client.
- **What I need from you:** Which system exports it (HaloPSA projects or another tool), and what the section should show (hours and cost per client, by phase?).
- **My recommendation:** Once the source is known CORE can read it.

### Devices: a lifecycle view (age by purchase date, warranty, replacement plan)  `r7-af-22`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Devices: a lifecycle view (age by purchase date, warranty, replacement plan)
- **What it affects:** Devices: age, warranty and replacement planning.
- **What I need from you:** Not started, needs data: Devices show warranty end dates when NinjaOne carries them, but no purchase date. Question: where is the purchase date kept (HaloPSA assets, Ninja custom field, a spreadsheet)? Without it age can only be shown from first seen.


### Personnel: training completion from Huntress awareness training  `r7-af-15`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Personnel: training completion from Huntress awareness training
- **What it affects:** Personnel page: whether each person finished security awareness training.
- **What I need from you:** Not started, needs data: Huntress awareness training gives learner counts, not who has finished. Question: is completion per person available in your Huntress SAT account (an API scope or an export)? If not, this cannot be built.


### Reports: a quarterly business review pack per client  `r7-af-31`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Reports: a quarterly business review pack per client
- **What it affects:** A quarterly review page or PDF per client combining service and security numbers.
- **What I need from you:** Not started, needs a decision: the Client review page is a security review (tool coverage, MFA, secure score, alerts, insurance checklist). A quarterly business review pack would add tickets, hours and satisfaction (Metrics > Client summary) and the finance view (revenue, margin) to it as one printable page per client. Question: include the finance numbers in something a client may see? Recommend: tickets, hours, satisfaction, security and what we did this quarter, without margin.


### A NinjaOne report of machines with no recent patch scan  `r7-cf-07`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A NinjaOne report of machines with no recent patch scan
- **What it affects:** A report of machines with no recent patch scan; needs a new NinjaOne read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. Device records carry NinjaOne's last contact but not the last patch scan; I would read NinjaOne's OS patch report.


### An agent skill for answering a customer security questionnaire from the answer library  `r7-cf-24`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** An agent skill for answering a customer security questionnaire from the answer library
- **What it affects:** Agents answering customer security questionnaires from your answer library; widens what agents can read.
- **What I need from you:** Decision for Hal: these four agent skills need a read tool for A.C.O.R.N's compliance data (questionnaires and answer library, access reviews, vendors, control tests). Agents have no compliance tools today, and a new read tool widens what CORE's key and the agents can reach (the same key reaches every client). Question: may agents read compliance data, for all clients or only the one in the conversation? My recommendation: read-only, one client at a time, through a new narrow key scope.


### An agent skill for the quarterly vendor review  `r7-cf-26`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** An agent skill for the quarterly vendor review
- **What it affects:** Agents running the quarterly vendor review; widens what agents can read.
- **What I need from you:** Decision for Hal: these four agent skills need a read tool for A.C.O.R.N's compliance data (questionnaires and answer library, access reviews, vendors, control tests). Agents have no compliance tools today, and a new read tool widens what CORE's key and the agents can reach (the same key reaches every client). Question: may agents read compliance data, for all clients or only the one in the conversation? My recommendation: read-only, one client at a time, through a new narrow key scope.


### An agent skill for writing the evidence note for an access review  `r7-cf-25`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** An agent skill for writing the evidence note for an access review
- **What it affects:** Agents writing evidence notes for access reviews; widens what agents can read.
- **What I need from you:** Decision for Hal: these four agent skills need a read tool for A.C.O.R.N's compliance data (questionnaires and answer library, access reviews, vendors, control tests). Agents have no compliance tools today, and a new read tool widens what CORE's key and the agents can reach (the same key reaches every client). Question: may agents read compliance data, for all clients or only the one in the conversation? My recommendation: read-only, one client at a time, through a new narrow key scope.


### An agent skill that explains an automated control test failure and the fix  `r7-cf-27`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** An agent skill that explains an automated control test failure and the fix
- **What it affects:** Agents explaining failed control tests; widens what agents can read.
- **What I need from you:** Decision for Hal: these four agent skills need a read tool for A.C.O.R.N's compliance data (questionnaires and answer library, access reviews, vendors, control tests). Agents have no compliance tools today, and a new read tool widens what CORE's key and the agents can reach (the same key reaches every client). Question: may agents read compliance data, for all clients or only the one in the conversation? My recommendation: read-only, one client at a time, through a new narrow key scope.


### CIPP: list guest users older than a year for each client  `r7-cf-08`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** CIPP: list guest users older than a year for each client
- **What it affects:** A report of old guest users per client; needs a new CIPP read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. I would read each client's guest users with their creation date through CIPP.


### CIPP: list mailboxes with a forwarding rule to an outside address (extend the existing check to a list)  `r7-cf-10`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** CIPP: list mailboxes with a forwarding rule to an outside address (extend the existing check to a list)
- **What it affects:** A list of mailboxes forwarding mail outside the company; needs a new CIPP read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. The existing check only reports a count; I would list the mailboxes and the outside addresses through CIPP.


### CIPP: list shared mailboxes with a sign-in enabled  `r7-cf-09`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** CIPP: list shared mailboxes with a sign-in enabled
- **What it affects:** A report of shared mailboxes that can sign in; needs a new CIPP read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. I would read shared mailboxes and whether sign-in is enabled through CIPP.


### IT Glue: find clients with no documented backup or no network diagram  `r7-cf-16`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** IT Glue: find clients with no documented backup or no network diagram
- **What it affects:** A list of clients with no documented backup or network diagram; needs IT Glue to be read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. IT Glue documents are not read by A.C.O.R.N today; I would read each client's documents and flag clients with none titled like backup or network diagram.


### Liongard: turn the disk and backup inspections into per-device lines with names  `r7-cf-11`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Liongard: turn the disk and backup inspections into per-device lines with names. Liongard alerts already name the affected disks and devices (the Datto backup check lists each system and days since the last backup).
- **What it affects:** Devices page, alerts and Client posture for Liongard-flagged items.
- **What I need from you:** What is missing: (a) a row on the Devices page for each flagged device, (b) one alert per device instead of one per client, or (c) device names on the Client posture checks?
- **My recommendation:** (c) first, it is the smallest.

### Meraki: list SSIDs with no encryption and clients that use them  `r7-cf-13`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Meraki: list SSIDs with no encryption and clients that use them
- **What it affects:** A list of open (unencrypted) Wi-Fi networks and who uses them; needs a new Meraki read.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. Meraki devices carry status and tags, not wireless settings; I would read each network's SSIDs and encryption setting.


### ThreatMate: weekly change report (new exposed services and vulnerabilities)  `r7-cf-15`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** ThreatMate: weekly change report (new exposed services and vulnerabilities)
- **What it affects:** A weekly change report of exposed services and vulnerabilities; A.C.O.R.N must start keeping a weekly copy.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. A weekly change report needs last week's list of exposed services and vulnerabilities to compare with; A.C.O.R.N keeps only the latest, so I would start keeping a weekly copy and the first report would be a week away.


### UniFi: report devices offline for more than a week  `r7-cf-14`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** UniFi: report devices offline for more than a week
- **What it affects:** A report of UniFi devices offline for over a week; needs CORE to remember when each went offline.
- **What I need from you:** Not started: A.C.O.R.N does not hold the data this needs, so CORE would have to read it from the vendor first, and I cannot verify a vendor read without a live look at the account. Reply 'go' in the box and I build it from the vendor's published API, marked NOT VERIFIED until you see real numbers. UniFi devices carry status but not how long they have been offline; I would keep when a device was first seen offline.


## Questions (1)

### Employee toolbox (from Rewst Tool Portal): client picker and Microsoft 365 action tiles  `rw-toolbox`
- **Area:** Security  |  **Added:** 2026-11-15  |  **Status:** not started
- **What it is:** Employee toolbox (from the Rewst Tool Portal): a client picker and Microsoft 365 action tiles (reset MFA, change password, remediation, out of office, mailbox permissions and more) as a launcher over CIPP actions with the approval path.
- **What it affects:** Real changes to client Microsoft 365 accounts; highest-risk item on the list.
- **What I need from you:** Which actions first, who may press them, whether every press needs approval, whether the user picker lists A.C.O.R.N identities, and whether scheduled workflows wait.
- **My recommendation:** Five tiles (reset MFA, change password, compromised-user remediation, out of office, mailbox permissions); every press creates an approval request.

## Decision (27)

### Audits: auditor sign-in and a data room (the audit tracker is built)  `audits-data-room`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The audit tracker is built (audits with evidence requests, owners, due dates, provided and accepted). Still missing: a sign-in for the external auditor and a place to keep the evidence files.
- **What it affects:** Compliance > Audits. Adds a new kind of user (auditor) and file storage (where evidence files live: cost, retention, who can read them).
- **What I need from you:** Does the auditor get their own sign-in limited to one audit? Where should the files be stored (A.C.O.R.N database, Azure storage, or stay as links to files elsewhere)?
- **My recommendation:** Auditor gets a read-only role limited to one audit; files kept in Azure blob storage per audit with a retention date. I can build this once you agree. See also r7-af-16 and r7-af-17, which are the same work split in two.

### Compliance in the client-facing part of A.C.O.R.N  `client-facing-compliance`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Show the Compliance section to your clients in their own sign-in, after it works for Live Oak.
- **What it affects:** What clients can see about their own compliance; needs the client sign-in (client_viewer role) already built for the customer dashboard.
- **What I need from you:** Who sees what: which compliance pages, read-only or editable, and whether all clients or chosen ones.
- **My recommendation:** Read-only compliance overview and policies for clients you choose, using the existing client sign-in with the authenticator app. See also r7-af-35 and r7-af-37.

### Trust center: a public share link (the signed-in trust center is built)  `trust-center`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The trust center page exists behind sign-in. A public link would let a prospect or customer view it without signing in.
- **What it affects:** Compliance > Trust center. A public address means anyone with the link can read what you choose to publish (policies, certifications, documents).
- **What I need from you:** Do you want a public link at all? If yes: one per client, which documents may be shown, and a switch to turn it off.
- **My recommendation:** One public link per client, off by default, with an off switch and a list of exactly which documents are shown. See also r7-af-18.

### Device merge search that finds a machine filed under a sibling client  `merge-search-sibling`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** The device merge search would also find a machine filed under a sibling client.
- **What it affects:** A merge across clients moves a record between clients, so it touches client data boundaries.
- **What I need from you:** Decide together with huntress-family.
- **My recommendation:** Do not build until families are decided.

### Follow a machine by name alone when it has a random Windows default name  `name-only-follow`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Follow a machine by name alone when Windows gave it a random default name (so a rename or re-image does not look like a new device).
- **What it affects:** Device identity and merging across tools; could wrongly join two machines that share a name.
- **What I need from you:** Whether following by name alone is acceptable, and under what condition (same client only?).
- **My recommendation:** Only within one client and only when the serial number is missing. Held with the families design.

### NinjaOne command console (CMD and PowerShell)  `ninja-console`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A NinjaOne command console (CMD and PowerShell) inside A.C.O.R.N.
- **What it affects:** Remote command execution on client machines: a high-risk capability; needs the approval path and audit.
- **What I need from you:** Your go-ahead and the rules (who, which clients, approval on every command?).
- **My recommendation:** Keep on hold.

### Parent and child clients (families) so New Waterloo and its NW - clients share group records  `huntress-family`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Parent and child clients (families), e.g. New Waterloo and its NW - clients, so group-level records follow to the child client when tools file same-named machines under siblings.
- **What it affects:** Devices, Huntress and every other tool's records for the family; also the ThreatMate zeros on Billing sync for the NW - locations.
- **What I need from you:** Your go-ahead to design families (it is held until you say). It also decides how a merge across clients is allowed (see merge-search-sibling).
- **My recommendation:** Start with a read-only family link (parent to children) used for reporting and counts before any record moves between clients.

### A client-facing portal with only the compliance pages  `r7-af-37`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A client-facing portal with only the compliance pages.
- **What it affects:** Same as client-facing-compliance.
- **What I need from you:** Decide with client-facing-compliance.
- **My recommendation:** -

### Audits: a data room of uploaded files per audit  `r7-af-17`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Audits: a data room of uploaded files per audit.
- **What it affects:** File storage; same as audits-data-room.
- **What I need from you:** Decide with audits-data-room.
- **My recommendation:** -

### Audits: a read-only auditor view limited to one audit  `r7-af-16`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Audits: a read-only auditor view limited to one audit.
- **What it affects:** A new sign-in type; same as audits-data-room.
- **What I need from you:** Decide with audits-data-room.
- **My recommendation:** -

### Policies: a staff acceptance page with a link per person  `r7-af-13`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Policies: a staff acceptance page with a link per person (each employee confirms they read a policy).
- **What it affects:** A public page per person; evidence of acceptance for audits.
- **What I need from you:** Go-ahead and whether e-mail sending is allowed (see policy reminders).
- **My recommendation:** Yes, with one-time links.

### Roles: a role for read-only compliance viewers  `r7-af-35`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Roles: a role for read-only compliance viewers.
- **What it affects:** Adds a role that sees compliance pages only.
- **What I need from you:** Go-ahead and the exact pages.
- **My recommendation:** Yes.

### Settings: an export and import of settings between organizations  `r7-af-34`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Settings: export and import of settings between organizations.
- **What it affects:** Copying settings from one organization or client to another; risk of copying secrets or wrong rules.
- **What I need from you:** Which settings may be copied (never secrets) and whether needed.
- **My recommendation:** Rules and frameworks only.

### Trust center: a public share link with an off switch  `r7-af-18`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Trust center: a public share link with an off switch.
- **What it affects:** Same as trust-center.
- **What I need from you:** Decide with trust-center.
- **My recommendation:** -

### Vendors: a questionnaire sent to the vendor as a form with a link  `r7-af-06`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Vendors: send a questionnaire to the vendor as a form with a link they fill in.
- **What it affects:** A public form (no sign-in) that outside parties fill; what vendor data is stored.
- **What I need from you:** Go-ahead and the questions to ask (or use the built-in questionnaire).
- **My recommendation:** Link expires after 30 days; answers saved to the vendor record.

### A per-client switch that requires single sign-on  `r7-ai-35`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A per-client switch that requires single sign-on (Microsoft) for that client's users.
- **What it affects:** Sign-in for that client's users; wrongly set it can lock them out.
- **What I need from you:** Which clients first, and whether password sign-in stays as a fallback for admins.
- **My recommendation:** Opt-in per client with an admin fallback.

### Decide how long audit logs are kept by default  `r7-ai-40`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Decide how long audit logs are kept by default.
- **What it affects:** Storage and what you can prove later; compliance frameworks often expect 12 months.
- **What I need from you:** A retention period (for example 12 or 24 months) and whether clients may choose their own.
- **My recommendation:** 12 months online, longer archived.

### Detected applications also from Google Workspace  `r7-ai-34`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Detected applications (SaaS apps found in use) also from Google Workspace, not only Microsoft.
- **What it affects:** Compliance > Vendors detected applications; needs Google Workspace access like google-bec-scan.
- **What I need from you:** Whether to build it and whether you will grant read access to Google Workspace app/OAuth data.
- **My recommendation:** Build after the Google access decision.

### A first-run wizard that checks each connector and says what is missing  `r7-cf-37`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A first-run wizard that checks each connector and says what is missing.
- **What it affects:** Setup experience for a new install; no change to existing ones.
- **What I need from you:** Go-ahead.
- **My recommendation:** Yes.

### Add a second CORE VM for failover  `r7-cf-40`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Add a second CORE VM for failover.
- **What it affects:** Azure cost (a second VM) and complexity: two CORE copies must not both act.
- **What I need from you:** Whether the extra cost and complexity are wanted.
- **My recommendation:** Not yet; the snapshots cover recovery.

### HaloPSA: create a ticket for a failing automated control test  `r7-cf-18`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** HaloPSA: create a ticket for a failing automated control test.
- **What it affects:** Ticket volume in Halo; needs a ticket type and priority.
- **What I need from you:** Whether to do it, for which client and what ticket type and priority.
- **My recommendation:** One ticket per failing test per client, deduplicated.

### HaloPSA: ticket-to-alert round trip: closing the ticket resolves the alert  `r7-cf-17`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** HaloPSA ticket to alert round trip: closing the ticket in Halo resolves the alert in A.C.O.R.N.
- **What it affects:** Alert status, and what your technicians see in Halo; risk of closing a real alert because a ticket was closed.
- **What I need from you:** Whether closing a ticket may resolve the alert automatically, for which alert types.
- **My recommendation:** Only when every alert in the case is already handled.

### Slack: post the morning summary of new critical alerts to a channel  `r7-cf-19`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Slack: post the morning summary of new critical alerts to a channel.
- **What it affects:** Posts content from client alerts into a Slack channel (who is in it matters).
- **What I need from you:** Whether to do it, the channel, the time and whether client names may appear.
- **My recommendation:** A private channel, 8:00, client names included.

### Windows: start with the machine as a service option  `r7-cf-30`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Windows: start CORE with the machine as a service option.
- **What it affects:** How CORE runs on the VM and restarts; permissions and auto-update behaviour.
- **What I need from you:** Go-ahead.
- **My recommendation:** Yes, as a service with auto-restart.

### Merge the duplicated connector descriptions into one source  `r7-ci-33`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Merge the duplicated connector descriptions (they live in more than one place) into one source.
- **What it affects:** CORE connectors list, docs and A.C.O.R.N connector cards; a refactor with no visible change.
- **What I need from you:** Go-ahead (low risk, internal).
- **My recommendation:** Yes.

### Move secrets from the .env file into the Windows credential store  `r7-ci-15`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Move secrets (API keys and tokens) from CORE's .env file into the Windows credential store.
- **What it affects:** How CORE starts and how updates work; secrets would no longer sit in a text file. Risk: a mistake could stop CORE from reading its keys.
- **What I need from you:** Whether to do it, and whether the VM may be restarted during the change.
- **My recommendation:** Worth doing; I would do it as an option that falls back to .env.

### Rename the old aisoc-* files to acorn-* in one reviewed batch  `r7-ci-38`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Rename the old aisoc-* files to acorn-* in one reviewed batch.
- **What it affects:** Many file names and imports in CORE and A.C.O.R.N; risk of breaking builds and old links.
- **What I need from you:** Go-ahead, and the moment (it should happen when you are away; see acorn-rename).
- **My recommendation:** Do it with acorn-rename steps 3 to 6 in one planned window.

## Proposal (33)

### 12.18: real playbooks  `real-playbooks`
- **Area:** Automation  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** 12.18: real playbooks
- **What it affects:** Automated response steps for alerts (isolate, disable, ticket); high-risk if wrong.
- **What I need from you:** Proposal, reply 'go' or change it: this is a large feature known only by its backlog number and has no written scope. Tell me in a few lines what it should do and who uses it, or point me at the backlog text, and I will plan it; otherwise it stays here.


### Send SOC 2, ISO 27001, PCI DSS and HIPAA requirements from CORE so their control health comes from Secureframe too  `secureframe-other-frameworks`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Send SOC 2, ISO 27001, PCI DSS and HIPAA requirements from CORE so their control health comes from Secureframe too
- **What it affects:** Control health for SOC 2, ISO 27001, PCI DSS and HIPAA would come from Secureframe as NIST CSF and CIS do now.
- **What I need from you:** Proposal, reply 'go' or change it: this is a large feature known only by its backlog number and has no written scope. Tell me in a few lines what it should do and who uses it, or point me at the backlog text, and I will plan it; otherwise it stays here.


### A6: weekly briefing paragraph  `weekly-briefing`
- **Area:** Reports  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A6: weekly briefing paragraph
- **What it affects:** Adds a weekly written summary for you or clients; which data goes in it and who receives it.
- **What I need from you:** Proposal, reply 'go' or change it: this is a large feature known only by its backlog number and has no written scope. Tell me in a few lines what it should do and who uses it, or point me at the backlog text, and I will plan it; otherwise it stays here.


### Billing: a margin forecast from the license counts  `r7-af-38`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Billing: a margin forecast from the license counts
- **What it affects:** Billing: a forward-looking margin per client from license counts.
- **What I need from you:** Not started, needs a definition: what should the forecast show? My reading: for each client, next month's revenue from its HaloPSA recurring invoice lines, the cost of the licenses counted for it (counts times each vendor's cost per license from Settings > Finance > Software costs) and the margin between them, flagged where the counts have changed since the invoice. Tell me if that is right, or what else (a trend over months? per vendor?). It also depends on vendors having counts chosen.


### Identities: a joiner and leaver report from the directory  `r7-af-25`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Identities: a joiner and leaver report from the directory
- **What it affects:** Identities: who joined and who left, by date.
- **What I need from you:** Not started, needs a history: a joiner and leaver report needs to know when each directory account appeared and disappeared; A.C.O.R.N keeps the current identities and first seen dates only. I would use first seen as the join date and mark an account as a leaver when it was disabled or left the directory (recording the day from now on). OK to start that way?


### Reports: schedule any report by email  `r7-af-32`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Reports: schedule any report by email
- **What it affects:** Reports sent by e-mail on a schedule; client names in e-mail.
- **What I need from you:** Not started, needs a decision: which reports can be scheduled (Executive digest, Client review, Net income tabs?), who receives them (a fixed list per report), the day and time, and whether client names may go out by e-mail. The mail sender used for the compliance notice can carry them.


### Query-plan tests for the devices list on a table with many rows  `r7-ai-02`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Query-plan tests for the devices list on a table with many rows
- **What it affects:** Devices list performance tests; as described it cannot be built because the list pages in memory.
- **What I need from you:** Proposal, reply 'go' or change it: query-plan tests for the devices list. Not possible as described: the devices list loads every device into memory and pages in Python, so there is no per-page query to plan. Close this item, or move the list to database paging (a large change)?


### Say license in every text the API and CORE produce, not only in the console  `r7-ai-01`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Say license in every text the API and CORE produce, not only in the console
- **What it affects:** Spelling of license in API and CORE text (about 120 places, many are field names).
- **What I need from you:** Proposal, reply 'go' or change it: say license in every text the API and CORE produce. About 120 places in the API still write the British spelling, but many are field names and identifiers (licence_waste, licence_counts) that other code depends on; I would change only user-visible text and keep identifiers. OK?


### A Cipher job that drafts the weekly client review paragraph from the data  `r7-cf-21`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A Cipher job that drafts the weekly client review paragraph from the data
- **What it affects:** A weekly paragraph per client drafted by the Cipher agent; model cost and who reads it.
- **What I need from you:** Proposal, reply 'go' or change it: a Cipher job that drafts the weekly client review paragraph from the data. Each scheduled agent job costs a model run per client per week and its text goes to a person. How many clients, and where should it be delivered?


### A Jax job that lists integrations whose last read is older than a day  `r7-cf-22`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A Jax job that lists integrations whose last read is older than a day
- **What it affects:** A daily agent message about stale integrations; model cost; the page already shows it.
- **What I need from you:** Proposal, reply 'go' or change it: a Jax job that lists integrations whose last read is older than a day. Platform health and Connectors already show this; a scheduled agent adds a model run a day. Wanted as a message, or is the page enough?


### A Vera job that checks every client has a Halo contact for security notices  `r7-cf-23`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A Vera job that checks every client has a Halo contact for security notices
- **What it affects:** A check that every client has a Halo contact for security notices.
- **What I need from you:** Proposal, reply 'go' or change it: a Vera job that checks every client has a Halo contact for security notices. Needs CORE to read each client's HaloPSA contacts; where should gaps be reported?


### A command that prints what CORE would send for one client without sending it  `r7-cf-35`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A command that prints what CORE would send for one client without sending it
- **What it affects:** A debugging command that prints what CORE would send for one client.
- **What I need from you:** Proposal, reply 'go' or change it: a command that prints what CORE would send for one client without sending it. Same entry as r7-ci-23 (--dry-run).


### A command to replay one sweep for one client for debugging  `r7-cf-34`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A command to replay one sweep for one client for debugging
- **What it affects:** A debugging command that replays one sweep for one client.
- **What I need from you:** Proposal, reply 'go' or change it: a command to replay one sweep for one client for debugging. Same entry as r7-ci-23 (a sweep script); do both together?


### A daily CORE self-report: what ran, what failed, what changed  `r7-cf-20`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A daily CORE self-report: what ran, what failed, what changed
- **What it affects:** A daily summary of what CORE did; where it is delivered.
- **What I need from you:** Proposal, reply 'go' or change it: a daily CORE self-report (what ran, what failed, what changed). The heartbeat on Platform health now shows commit, uptime and passes. Where should the report go: a Platform health panel, an e-mail, or a Slack message?


### A local read-only page listing the connectors and when each last read  `r7-cf-31`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A local read-only page listing the connectors and when each last read
- **What it affects:** A local page on the CORE machine listing connectors.
- **What I need from you:** Proposal, reply 'go' or change it: a local read-only page listing the connectors and when each last read. Platform health shows this in A.C.O.R.N; a local page helps only when A.C.O.R.N is unreachable. Wanted?


### A weekly report of every device whose Huntress organization differs from its NinjaOne client, sent to A.C.O.R.N  `r7-cf-01`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A weekly report of every device whose Huntress organization differs from its NinjaOne client, sent to A.C.O.R.N
- **What it affects:** A weekly report of the 141-style Huntress organization mismatches, shown in A.C.O.R.N.
- **What I need from you:** Proposal, reply 'go' or change it: a weekly report of devices whose Huntress organization differs from the NinjaOne client. The list of 141 machines was built by hand from live reads; I would move that logic into a weekly CORE report posted to A.C.O.R.N and shown on Device Versions. Needs the live reads, so I cannot test against real data tonight.


### Offline mode: queue feed posts while A.C.O.R.N is unreachable and send them in order  `r7-cf-33`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Offline mode: queue feed posts while A.C.O.R.N is unreachable and send them in order
- **What it affects:** How CORE behaves when A.C.O.R.N is unreachable (queue and replay).
- **What I need from you:** Proposal, reply 'go' or change it: offline mode: queue feed posts while A.C.O.R.N is unreachable and send them in order. It must not resend stale data or fill the disk; proposal: keep at most 24 hours, newest state per route. OK?


### Saved ScreenConnect commands (reboot, flush DNS, gpupdate) with a confirm step  `r7-cf-05`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Saved ScreenConnect commands (reboot, flush DNS, gpupdate) with a confirm step
- **What it affects:** ScreenConnect: saved commands (reboot, flush DNS, gpupdate) on client machines.
- **What I need from you:** Proposal, reply 'go' or change it: saved ScreenConnect commands (reboot, flush DNS, gpupdate) with a confirm step. Remote command execution; which commands and who may run them?


### Send a ScreenConnect command to several machines at once with each answer listed  `r7-cf-04`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Send a ScreenConnect command to several machines at once with each answer listed
- **What it affects:** ScreenConnect: running one command on several client machines at once (high risk).
- **What I need from you:** Proposal, reply 'go' or change it: send a ScreenConnect command to several machines at once with each answer listed. Remote command execution on many machines; needs the approval path and a cap. Who may use it and what cap?


### Support bundle: a zip of logs and settings names with secrets masked  `r7-cf-36`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Support bundle: a zip of logs and settings names with secrets masked
- **What it affects:** A support zip of logs and setting names; must never contain secrets.
- **What I need from you:** Proposal, reply 'go' or change it: a support bundle: a zip of logs and settings names with secrets masked. Needs a rule for what counts as a secret in a log line. Proposal: mask anything matching the existing secret scanner and never include .env. OK?


### Windows: a tray menu entry showing sweep status and the last update  `r7-cf-29`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Windows: a tray menu entry showing sweep status and the last update
- **What it affects:** A Windows tray icon for CORE.
- **What I need from you:** Proposal, reply 'go' or change it: a Windows tray menu entry showing sweep status and the last update. CORE already has a window; a tray icon adds an always-on process. Wanted?


### A module dependency graph doc and a test that fails on an import cycle  `r7-ci-30`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A module dependency graph doc and a test that fails on an import cycle
- **What it affects:** A dependency graph document and cycle check of CORE's modules; a script outside verify.
- **What I need from you:** Proposal, reply 'go' or change it: a module dependency graph doc and a test that fails on an import cycle. The test has to read import lines from source text, which the project's test rules forbid; a script run by verify would be allowed only if you change the rules. OK as a script outside verify?


### A script that simulates a bad update so the watchdog rollback is proven, not assumed  `r7-ci-06`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A script that simulates a bad update so the watchdog rollback is proven, not assumed
- **What it affects:** A deliberate failed deploy on the real CORE VM to prove rollback; a short outage.
- **What I need from you:** Proposal, reply 'go' or change it: a script that deliberately ships a build that fails its health check, to prove the watchdog rolls back. It would run on the real VM and cause a short outage. OK to run it in a quiet window, and which?


### A shared CIPP read cache keyed by tenant and endpoint to cut 429 answers  `r7-ci-16`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A shared CIPP read cache keyed by tenant and endpoint to cut 429 answers
- **What it affects:** CIPP read volume and 429 (slow-down) answers; a shared cache could show slightly old CIPP data.
- **What I need from you:** Proposal, reply 'go' or change it: a shared CIPP read cache keyed by tenant and endpoint to cut 429 answers. I cannot measure 429s without a live CIPP; the 429 rate over the last week would show whether it is needed. Do you see 429s in the CORE log?


### A test that every shell command call site is on a reviewed allowlist  `r7-ci-32`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A test that every shell command call site is on a reviewed allowlist
- **What it affects:** A reviewed list of every place CORE runs a shell command; a script and an allowlist file.
- **What I need from you:** Proposal, reply 'go' or change it: a check that every shell command call site is on a reviewed allowlist. Same source-text rule as r7-ci-30. scripts/spawn-sites.mjs already lists spawn sites; extend it with an allowlist file?


### Check A.C.O.R.N answers against the expected shape and log drift  `r7-ci-11`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Check A.C.O.R.N answers against the expected shape and log drift
- **What it affects:** Every reply CORE gets from A.C.O.R.N would be checked and logged; a little extra work per send.
- **What I need from you:** Proposal, reply 'go' or change it: after each A.C.O.R.N reply CORE checks it against the expected shape and logs drift. Adds a check to every send; the contract tests already cover the shapes CORE sends. Worth it, or leave to the contract tests?


### Every sweep command-line entry accepts --dry-run  `r7-ci-23`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Every sweep command-line entry accepts --dry-run
- **What it affects:** A new command-line script for the sweeps; nothing changes for users.
- **What I need from you:** Proposal, reply 'go' or change it: every sweep entry accepts --dry-run (read and work out, send nothing). CORE has no command-line entry per sweep today (jobs.mjs only lists results). I would add one script, node scripts/sweep.mjs <tool> --dry-run [--client X]. OK?


### List the modules whose Windows-only paths have no path.win32 test, then add them  `r7-ci-26`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** List the modules whose Windows-only paths have no path.win32 test, then add them
- **What it affects:** A report of which Windows-only code has no Windows-path test; a script, not a test.
- **What I need from you:** Proposal, reply 'go' or change it: list the modules whose Windows-only paths have no path.win32 test. That needs a tool that reads source text to find them, which the project's test rules forbid in tests; I would make it a script, not a test. OK as a script?


### One module reads environment keys by name, replacing scattered process.env reads  `r7-ci-10`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** One module reads environment keys by name, replacing scattered process.env reads
- **What it affects:** Every place CORE reads settings from the environment; a wide internal refactor.
- **What I need from you:** Proposal, reply 'go' or change it: one module reads environment keys by name and the scattered process.env reads move to it. A wide refactor of CORE with no visible change; risk is a missed key. OK to do it in one reviewed batch (with the rename window)?


### Show each vendor's remaining daily read budget on the health page  `r7-ci-17`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Show each vendor's remaining daily read budget on the health page
- **What it affects:** A Platform health line per vendor; needs vendors to report quota.
- **What I need from you:** Proposal, reply 'go' or change it: show each vendor's remaining daily read budget on Platform health. Needs CORE to report each vendor's remaining quota (most vendors do not publish it). Which vendors do you hit limits with?


### update_core keeps the last three builds and offers a one-command rollback  `r7-ci-05`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** update_core keeps the last three builds and offers a one-command rollback
- **What it affects:** How CORE is updated and recovered on its VM (the deploy script is on the verify gate's protected list); disk use.
- **What I need from you:** Proposal, reply 'go' or change it: keep the last three CORE builds on the VM and add a one-command rollback to update-core-vm. It changes the deploy script (which the verify gate treats as sensitive) and uses disk (about 1.5 GB a build). OK to touch the deploy script?


### 12.14: threat hunting  `threat-hunting`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** 12.14: threat hunting
- **What it affects:** Saved hunts and scheduled searches across client alert data.
- **What I need from you:** Proposal, reply 'go' or change it: this is a large feature known only by its backlog number and has no written scope. Tell me in a few lines what it should do and who uses it, or point me at the backlog text, and I will plan it; otherwise it stays here.


### 12.19: file integrity monitoring baselines  `fim-baselines`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** 12.19: file integrity monitoring baselines
- **What it affects:** File integrity monitoring: a baseline of important files per client and alerts when they change.
- **What I need from you:** Proposal, reply 'go' or change it: this is a large feature known only by its backlog number and has no written scope. Tell me in a few lines what it should do and who uses it, or point me at the backlog text, and I will plan it; otherwise it stays here.

