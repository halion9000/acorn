# Items waiting on Hal (after your replies in core2.docx)

33 items wait on you. 45 are open on my side (last sheet of the spreadsheet). Reply to any item in the text box under it on Settings > Upcoming improvements; I read the replies at the start of each session.

## Action for you (3)

### Move Huntress agents to the organization that matches their NinjaOne client  `huntress-moves`
- **Area:** Devices  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** About 141 machines are filed in a different Huntress organization than the client NinjaOne files them under. The Huntress API does not move agents (tested on BHRC-FM-01).
- **What it affects:** Huntress organizations and therefore Billing sync counts for Huntress and SAT lines.
- **What I need from you:** Moved some, more remain. Automating: the Huntress API cannot move an agent, so it cannot be fully automatic. What I can do is send the weekly list of mismatched machines (r7-cf-01) with the target organization filled in, so you move them in one pass. ESW Texas Subs: you say ESW Texas Subs is part of ESW Enterprise, so those 21 should map to ESW Enterprise and need no move. I am checking the mapping; Question: confirm the target for the Texas Subs machines is ESW Enterprise.


### Deploy NinjaOne to a Mac: try the package path on a test Mac  `r7-cf-03`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Deploy NinjaOne to a Mac: try the package path on a test Mac.
- **What it affects:** Mac installs of the NinjaOne agent from A.C.O.R.N.
- **What I need from you:** No reply yet. Needs a test Mac: press Deploy NinjaOne on it and tell me what happened.


### Rotate the CORE feed token and update both sides  `r7-ci-36`
- **Area:** Round 7: CORE improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Rotate the CORE feed token (the secret in the address CORE posts to) and update both sides.
- **What it affects:** Briefly stops CORE reporting to A.C.O.R.N until both sides hold the new token. A leaked token lets anyone post as CORE.
- **What I need from you:** Why: the feed token is the secret CORE posts with; anyone holding it can post fake data as CORE. It sits in CORE's .env and in logs. Rotating limits the damage if it ever leaked. Nothing shows it did leak. Recommend: do it once in a quiet hour soon, then yearly or when someone with access leaves. Reply 'now', give a time, or reply 'skip' and I close it.


## Check by you (2)

### SimpleSat: customer satisfaction in CORE and A.C.O.R.N, with reviews on each person  `simplesat-connector`
- **Area:** Metrics  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** SimpleSat customer satisfaction connector in CORE and A.C.O.R.N (CORE reads responses, A.C.O.R.N shows them on Metrics and on each person).
- **What it affects:** Metrics and people pages; built from SimpleSat's published file, not yet read against the live account.
- **What I need from you:** Logo already in both projects (nothing to add). Remaining: confirm CORE's first daily SimpleSat read worked (Metrics and a person's reviews).


### Customer-facing dashboard (from Rewst End User Dashboard): summary, labor hours, customer satisfaction per client  `rw-customer-dashboard`
- **Area:** Reports  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Customer-facing dashboard: the client sign-in (client_viewer role plus authenticator app) and /client-portal showing a company's tickets, hours and satisfaction.
- **What it affects:** What a client sees about themselves; it has not been verified live.
- **What I need from you:** Plain steps: 1) Settings > Users > create a user with the client_viewer role for one client's contact; 2) open A.C.O.R.N in a private window, sign in as that user, set up the authenticator app; 3) open the client portal and compare tickets, hours and satisfaction with Metrics > Client summary for that client. Tell me whether the numbers match. If you would rather I do the setup, say so.


## Review by you (2)

### Read the six policy templates and say what to change  `policy-wording-review`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Six policy templates: Information Security, Acceptable Use, Access Control, Incident Response, Vendor Management, Backup and Disaster Recovery (Compliance > Policies > Start a policy from a template).
- **What it affects:** The wording every client policy starts from.
- **What I need from you:** No reply received yet; the six templates are under Compliance > Policies > Start a policy from a template.


### Sales and Finance > Profitability and Net income: client profit by month from Halo, typed or QuickBooks costs, and the finance workbook's other sheets  `rw-profitability`
- **Area:** Sales and Finance  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Profitability and Net income with their tabs. Now built: Revenue to net income, New clients, By industry, Hours, Ranking, Client summary, P&L, QBO Profitability, Historical client revenue, QBO Travel, Hardware COGS, Inputs, Settings > Finance, add-on and support software by license counts.
- **What it affects:** Finance numbers you read and decide on.
- **What I need from you:** Yes, send the older Excel reports: I will compare them with the live tabs month by month and list differences. Put them in a new message (files attached to a reply box cannot be read).


## Go-ahead (1)

### Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6)  `acorn-rename`
- **Area:** Platform  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6 of docs/RENAME_AUDIT_2026-11-15.md change names other things depend on: folders, package names, container names, URLs).
- **What it affects:** Almost everything: builds, deploy scripts, the VM, links. Needs a window when you are away.
- **What I need from you:** Hal (core2.docx, 2026-11-18): 'Do it tonight at 10pm PT'. I will NOT run steps 4 to 6 on my own tonight, because they change live state (container names, database tables and the role, VM paths) and a mistake takes both apps down: each needs a database backup, a rollback script and someone watching. What I can safely do in that window, and will prepare for you to say go on: step 3 (new CORE_ and ACORN_ variable names with the old ones as fallbacks; no behavior change). Question: reply 'go 3' for step 3 tonight and tell me when you are at the keyboard for the rest; I will then do one of steps 4, 5 and 6 per window, each with a backup first, and the rename lands over a few evenings instead of one night.


## Access and decision (1)

### Google Workspace BEC: full mailbox scan  `google-bec-scan`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A full Google Workspace mailbox scan for business email compromise. ThreatMate cannot read mailboxes and the light Google check is on hold.
- **What it affects:** Client Google Workspace mailboxes: reads mail, so a privacy and consent matter.
- **What I need from you:** Exact steps are in docs/GOOGLE_BEC_SETUP.md (Google Cloud service account, domain-wide delegation, Gmail read scope, per client). I am writing it now; tell me the first client when you have done step 1.


## Question (4)

### Send SOC 2, ISO 27001, PCI DSS and HIPAA requirements from CORE so their control health comes from Secureframe too  `secureframe-other-frameworks`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Send SOC 2, ISO 27001, PCI DSS and HIPAA requirements from CORE so their control health comes from Secureframe too
- **What it affects:** Control health for SOC 2, ISO 27001, PCI DSS and HIPAA would come from Secureframe as NIST CSF and CIS do now.
- **What I need from you:** I checked: that was only copying the requirements text into A.C.O.R.N, which is already done. This item is the second step: control health (pass/fail per requirement) for SOC 2, ISO 27001, PCI DSS and HIPAA coming from Secureframe the way NIST CSF and CIS do now. Do you want that too? Reply 'go' or 'skip'.


### Net income: an Onboarding section (the workbook's Onboarding tab)  `finance-onboarding-tab`
- **Area:** Finance  |  **Added:** 2026-11-18  |  **Status:** new
- **What it is:** The workbook's Onboarding tab is a list of time entries on onboarding projects (773 rows from April 2026: user, role, customer, project, phase, task, effort, tracked time, billable, category, notes, approved).
- **What it affects:** A possible new Net income section: onboarding hours and labor cost per client.
- **What I need from you:** What I saw: the finance workbook has a tab called Onboarding with 773 rows from April 2026: user, role, customer, project, phase, task, effort, tracked time, billable, category, notes, approved. It looks like an export of time entries on onboarding projects. Question: which system does it come from (HaloPSA projects, Rewst, or something else)? If HaloPSA, I read project time entries from Halo directly and show hours and cost per client and phase.


### Devices: a lifecycle view (age by purchase date, warranty, replacement plan)  `r7-af-22`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Devices: a lifecycle view (age by purchase date, warranty, replacement plan)
- **What it affects:** Devices: age, warranty and replacement planning.
- **What I need from you:** No purchase date, so age comes from first seen plus warranty when available. I will build the lifecycle view that way and label it first seen. Reply 'go' to approve.


### 12.14: threat hunting  `threat-hunting`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** 12.14: threat hunting
- **What it affects:** Saved hunts and scheduled searches across client alert data.
- **What I need from you:** Threat hunting would let you save a search over client alert data (for example 'every sign-in from a new country this week') and run it on a schedule. Reply 'go' for a first version (saved searches plus a daily run), or 'skip'.


## Decision (10)

### Audits: auditor sign-in and a data room (the audit tracker is built)  `audits-data-room`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The audit tracker is built (audits with evidence requests, owners, due dates, provided and accepted). Still missing: a sign-in for the external auditor and a place to keep the evidence files.
- **What it affects:** Compliance > Audits. Adds a new kind of user (auditor) and file storage (where evidence files live: cost, retention, who can read them).
- **What I need from you:** Built: Compliance > Audits > open an audit > Auditor sign-in (create the account, temporary password shown once) and Files. The auditor signs in, sets up an authenticator app and sees only the audits opened to them (accept or send back requests, download and add files). Files are stored in A.C.O.R.N (10 MB each, 50 per audit). NOT checked in the running app: please create a test auditor on one audit, sign in as that account in a private window and tell me what you see.


### Trust center: a public share link (the signed-in trust center is built)  `trust-center`
- **Area:** Compliance  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The trust center page exists behind sign-in. A public link would let a prospect or customer view it without signing in.
- **What it affects:** Compliance > Trust center. A public address means anyone with the link can read what you choose to publish (policies, certifications, documents).
- **What I need from you:** Hal (core2.docx, 2026-11-18): yes to a public link: one per client, off by default, an off switch, a list of the documents shown. One catch before I build it: A.C.O.R.N only answers from allowed IP addresses, so a prospect outside could not open a public link. Question: may I open one public path that serves only the trust page (nothing else, nothing signed-in), through the same load balancer, with its own rule? If yes I build the page, the per-client token and the off switch, and give you the one infrastructure change to approve. If no, the link works only from allowed addresses.


### Audits: a data room of uploaded files per audit  `r7-af-17`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** Audits: a data room of uploaded files per audit.
- **What it affects:** File storage; same as audits-data-room.
- **What I need from you:** Built together with audits-data-room (see that item for what to check).


### Audits: a read-only auditor view limited to one audit  `r7-af-16`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** Audits: a read-only auditor view limited to one audit.
- **What it affects:** A new sign-in type; same as audits-data-room.
- **What I need from you:** Built together with audits-data-room (see that item for what to check).


### Policies: a staff acceptance page with a link per person  `r7-af-13`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Policies: a staff acceptance page with a link per person (each employee confirms they read a policy).
- **What it affects:** A public page per person; evidence of acceptance for audits.
- **What I need from you:** Both can be done: one-time e-mail links, or sign-in with Microsoft (SSO) so the click records who accepted. Recommend SSO for Live Oak staff and one-time links for outside people. Reply 'go' to build that.


### Settings: an export and import of settings between organizations  `r7-af-34`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Settings: export and import of settings between organizations.
- **What it affects:** Copying settings from one organization or client to another; risk of copying secrets or wrong rules.
- **What I need from you:** It would copy rules (alert rules, suppressions, which frameworks are on) from one client or organization to another, never keys or secrets. Useful when setting up a new client like an existing one. Reply 'go' to build it, or 'skip'.


### Vendors: a questionnaire sent to the vendor as a form with a link  `r7-af-06`
- **Area:** Round 7: A.C.O.R.N feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** Vendors: send a questionnaire to the vendor as a form with a link they fill in.
- **What it affects:** A public form (no sign-in) that outside parties fill; what vendor data is stored.
- **What I need from you:** Hal (core2.docx): sounds good, but will it work with the VPN / specific IP setup? Answer: no, not as it is. A vendor outside the allowed addresses cannot open a form link. Same fix as trust-center: one public path that serves only the vendor form (answers are saved, the link expires after 30 days). Reply with the answer given on trust-center and I build both together; otherwise the questionnaire can be e-mailed as a file instead.


### A per-client switch that requires single sign-on  `r7-ai-35`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A per-client switch that requires single sign-on (Microsoft) for that client's users.
- **What it affects:** Sign-in for that client's users; wrongly set it can lock them out.
- **What I need from you:** What it is for: it would force a client's users to sign in with their Microsoft account only (no A.C.O.R.N passwords) for the client sign-in. Only matters once clients log in (customer dashboard, client compliance). Recommend: defer until the client sign-in is live. Reply 'defer' or 'go'.


### Decide how long audit logs are kept by default  `r7-ai-40`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Decide how long audit logs are kept by default.
- **What it affects:** Storage and what you can prove later; compliance frameworks often expect 12 months.
- **What I need from you:** Archived = older audit log rows moved out of the live database into Azure blob storage (cheap, kept read-only, retrievable on request). Recommend 12 months online, 7 years archived for compliance. OK? Reply 'ok' or give other numbers.


### Detected applications also from Google Workspace  `r7-ai-34`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Detected applications (SaaS apps found in use) also from Google Workspace, not only Microsoft.
- **What it affects:** Compliance > Vendors detected applications; needs Google Workspace access like google-bec-scan.
- **What I need from you:** Same access as google-bec-scan: the same service account with the Admin SDK tokens scope lists apps people authorized. I will add that scope to the instructions in docs/GOOGLE_BEC_SETUP.md, so one setup covers both.


## Proposal (10)

### A6: weekly briefing paragraph  `weekly-briefing`
- **Area:** Reports  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A6: weekly briefing paragraph
- **What it affects:** Adds a weekly written summary for you or clients; which data goes in it and who receives it.
- **What I need from you:** A6 (weekly briefing) is a written summary: which clients had what alerts, what changed, what is open. It overlaps with r7-cf-21 and the report scheduler (r7-af-32). Recommend: fold it into the report scheduler instead of a separate feature. Reply 'fold' or 'skip'.


### Query-plan tests for the devices list on a table with many rows  `r7-ai-02`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Query-plan tests for the devices list on a table with many rows
- **What it affects:** Devices list performance tests; as described it cannot be built because the list pages in memory.
- **What I need from you:** If we did it, the devices list would load one page at a time from the database instead of loading every device and paging in the program. Benefit: faster pages and less memory as the device count grows (you have thousands). It is a large change; today's speed is acceptable. Recommend: leave it. Reply 'do it' or I close it.


### A Cipher job that drafts the weekly client review paragraph from the data  `r7-cf-21`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A Cipher job that drafts the weekly client review paragraph from the data
- **What it affects:** A weekly paragraph per client drafted by the Cipher agent; model cost and who reads it.
- **What I need from you:** Each Monday a draft paragraph per client could go to Slack (a channel) or e-mail to the account owner. About one model run per client per week. Reply with where it should go (Slack channel name or e-mail) or 'skip'.


### A daily CORE self-report: what ran, what failed, what changed  `r7-cf-20`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** A daily CORE self-report: what ran, what failed, what changed
- **What it affects:** A daily summary of what CORE did; where it is delivered.
- **What I need from you:** Built: CORE posts one short report a day to the CORE Slack channel (the same channel as the not-met check notices): what it runs, uptime, how many tool sweeps ran and sent, which had failures, which have not run in over a day. After 07:00 local, once a day, starting the day after this CORE update. NOT seen live: tell me what the first message looks like, or what to change.


### CIPP: list guest users older than a year for each client  `r7-cf-08`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** CIPP: list guest users older than a year for each client
- **What it affects:** A report of old guest users per client; needs a new CIPP read.
- **What I need from you:** Built (CIPP posture check with the names listed under Settings > Client posture > Microsoft 365 / CIPP). NOT VERIFIED against the live CIPP: after CORE's next CIPP pass, open a client's checks and see whether the list looks right. Check name: Guest accounts older than a year.


### CIPP: list mailboxes with a forwarding rule to an outside address (extend the existing check to a list)  `r7-cf-10`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** CIPP: list mailboxes with a forwarding rule to an outside address (extend the existing check to a list)
- **What it affects:** A list of mailboxes forwarding mail outside the company; needs a new CIPP read.
- **What I need from you:** Built (CIPP posture check with the names listed under Settings > Client posture > Microsoft 365 / CIPP). NOT VERIFIED against the live CIPP: after CORE's next CIPP pass, open a client's checks and see whether the list looks right. Check name: Mailboxes forwarding outside (separate from the mailbox-rule check).


### CIPP: list shared mailboxes with a sign-in enabled  `r7-cf-09`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** CIPP: list shared mailboxes with a sign-in enabled
- **What it affects:** A report of shared mailboxes that can sign in; needs a new CIPP read.
- **What I need from you:** Built (CIPP posture check with the names listed under Settings > Client posture > Microsoft 365 / CIPP). NOT VERIFIED against the live CIPP: after CORE's next CIPP pass, open a client's checks and see whether the list looks right. Check name: Shared mailboxes with sign-in on.


### IT Glue: find clients with no documented backup or no network diagram  `r7-cf-16`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** IT Glue: find clients with no documented backup or no network diagram
- **What it affects:** A list of clients with no documented backup or network diagram; needs IT Glue to be read.
- **What I need from you:** Built (CORE reads each client's IT Glue documents once a day; the check 'Backup and network diagram documents' is met with a document titled like a backup plan and one titled like a network diagram, partly with one, not met with neither). Judged by document titles only. NOT verified against live IT Glue (the document list endpoint is from IT Glue's reference): after the next daily IT Glue pass, open a client's checks and see whether it looks right.


### UniFi: report devices offline for more than a week  `r7-cf-14`
- **Area:** Round 7: CORE feature  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** UniFi: report devices offline for more than a week
- **What it affects:** A report of UniFi devices offline for over a week; needs CORE to remember when each went offline.
- **What I need from you:** Built on the A.C.O.R.N side: Reports > Device Versions has a new list of UniFi devices offline for more than a week. UniFi only says 'offline', never since when, so A.C.O.R.N counts from the day it first saw the device offline; the list starts empty and fills a week after the deploy. NOT checked against live UniFi data: check in a week that devices you know are down appear.


### 12.19: file integrity monitoring baselines  `fim-baselines`
- **Area:** Security  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** 12.19: file integrity monitoring baselines
- **What it affects:** File integrity monitoring: a baseline of important files per client and alerts when they change.
- **What I need from you:** File integrity monitoring: record a baseline of key files on client machines and alert when they change. It needs an agent on each machine that we do not run (Huntress and Ninja do not expose it). Recommend: skip for now. Reply 'skip' or 'go'.

