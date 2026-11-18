# Items waiting on Hal (as of 2026-11-18)

48 items wait on you. 56 more are open on my side with nothing needed from you (second sheet of the spreadsheet; I have not finished them). Source: the live Upcoming improvements list.

Reply to any of them in the text box under the item on Settings > Upcoming improvements and I read it at the start of the next session.

## Action for you (9)

### Move Huntress agents to the organization that matches their NinjaOne client  `huntress-moves`
- **Area:** Devices  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** About 141 machines are filed in a different Huntress organization than the client NinjaOne files them under. The Huntress API does not move agents (tested on BHRC-FM-01).
- **What it affects:** Huntress organizations and therefore Billing sync counts for Huntress and SAT lines.
- **What I need from you:** Move the agents by hand in the Huntress console from the list I sent (141 machines; 22 have no target organization mapped yet, mostly the 21 Texas Subs machines). Tell me the target organization for the 22.
- **My recommendation / default:** Nothing for me to build until the 22 targets are known.

### Qdrant server upgrade (6A39)  `qdrant-upgrade`
- **Area:** Platform  |  **Waiting on:** Action for you (calendar)  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Upgrade the Qdrant vector database server (item 6A39), after the Sunday 15 Nov snapshot.
- **What it affects:** Leafy and the agents' memory search while it is down.
- **What I need from you:** Pick the time window and approve the upgrade; the snapshot that was due is the safety net.
- **My recommendation / default:** A Sunday evening after a fresh snapshot.

### Check sign-in after the cookie change: sign in, sign out, and open Live graph  `a15-live-check`
- **Area:** Platform  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Check sign-in after the cookie change: sign in, reload, sign out. In the browser developer tools (Application) there should be no aisoc.responder.accessToken in local storage and two cookies (aisoc_access, aisoc_refresh).
- **What it affects:** Everyone's sign-in, Microsoft sign-in and the Live graph page.
- **What I need from you:** Try it and tell me what you see.
- **My recommendation / default:** -

### Rotate the CORE feed token and update both sides  `r7-ci-36`
- **Area:** Round 7: CORE improvement  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Rotate the CORE feed token (the secret in the address CORE posts to) and update both sides.
- **What it affects:** Briefly stops CORE reporting to A.C.O.R.N until both sides hold the new token. A leaked token lets anyone post as CORE.
- **What I need from you:** Choose a time, and generate or approve the new token (I must not see or print it).
- **My recommendation / default:** Do it in a quiet hour; I script the change on both sides.

### Install CORE on a clean Windows machine from the installer and note what breaks  `r7-ci-37`
- **Area:** Round 7: CORE improvement  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Install CORE on a clean Windows machine from the installer and note what breaks.
- **What it affects:** Confirms a new colleague or a rebuilt VM could install CORE.
- **What I need from you:** Provide a clean Windows machine (or VM) and run the installer, or give me access to do it.
- **My recommendation / default:** Use a throwaway Azure VM.

### Deploy NinjaOne to a Mac: try the package path on a test Mac  `r7-cf-03`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Deploy NinjaOne to a Mac: try the package path on a test Mac.
- **What it affects:** Mac installs of the NinjaOne agent from A.C.O.R.N.
- **What I need from you:** Provide a test Mac and press Deploy, tell me what happened.
- **My recommendation / default:** -

### Test the Cloudflare canary with a real honeytoken visit from outside  `r7-cf-38`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Test the Cloudflare canary with a real honeytoken visit from outside (a decoy link that should raise an alert).
- **What it affects:** Confirms the canary alert reaches A.C.O.R.N.
- **What I need from you:** Visit the honeytoken address from outside the network and tell me what alert appears.
- **My recommendation / default:** -

### Mobile: push notification for a critical alert  `r7-af-39`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Mobile: push notification for a critical alert.
- **What it affects:** Needs a mobile app or web push; depends on the mobile plan.
- **What I need from you:** Decide with r7-ai-36 (the mobile plan), and provide an Apple or Google developer account if an app is wanted.
- **My recommendation / default:** Web push first.

### Test Deploy NinjaOne on SCHKNOWCROSS  `ninja-deploy-test`
- **Area:** Devices  |  **Waiting on:** Action for you  |  **Added:** 2026-11-14  |  **Status:** shown completed on the live page
- **What it is:** Deploy NinjaOne (install the NinjaOne agent from A.C.O.R.N on a machine). The install now runs detached (CORE bc25a2c).
- **What it affects:** Remote install on a real machine (SCHKNOWCROSS).
- **What I need from you:** Press Deploy NinjaOne on SCHKNOWCROSS and tell me what the machine printed. (The live list shows this item marked completed by you; confirm it worked.)
- **My recommendation / default:** If it worked, nothing more is needed.

## Check by you (3)

### Customer-facing dashboard (from Rewst End User Dashboard): summary, labor hours, customer satisfaction per client  `rw-customer-dashboard`
- **Area:** Reports  |  **Waiting on:** Check by you  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Customer-facing dashboard: the client sign-in (client_viewer role plus authenticator app) and /client-portal showing a company's tickets, hours and satisfaction.
- **What it affects:** What a client sees about themselves; it has not been verified live.
- **What I need from you:** Create one client sign-in for a client linked to HaloPSA, sign in, set up the authenticator app and check the numbers match Metrics > Client summary for that client.
- **My recommendation / default:** -

### SaaS billing sync (from Rewst saas-billing): approve license-count differences and push them to HaloPSA  `rw-billing-sync`
- **Area:** Billing  |  **Waiting on:** Check by you  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Billing sync approvals: approving a line makes CORE set the client's recurring invoice in HaloPSA to the counted quantity.
- **What it affects:** Real invoices in HaloPSA; not verified live.
- **What I need from you:** Give someone the Billing role and watch the first approval in Halo (the quantity, and that the other lines stayed).
- **My recommendation / default:** Also decide how to handle the NW - ThreatMate zeros (see huntress-family).

### SimpleSat: customer satisfaction in CORE and A.C.O.R.N, with reviews on each person  `simplesat-connector`
- **Area:** Metrics  |  **Waiting on:** Check by you  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** SimpleSat customer satisfaction connector in CORE and A.C.O.R.N (CORE reads responses, A.C.O.R.N shows them on Metrics and on each person).
- **What it affects:** Metrics and people pages; built from SimpleSat's published file, not yet read against the live account.
- **What I need from you:** Confirm the daily read works and send the SimpleSat logo in a new message (images sent mid-turn are not saved).
- **My recommendation / default:** -

## Review by you (3)

### Read the six policy templates and say what to change  `policy-wording-review`
- **Area:** Compliance  |  **Waiting on:** Review by you  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Six policy templates: Information Security, Acceptable Use, Access Control, Incident Response, Vendor Management, Backup and Disaster Recovery (Compliance > Policies > Start a policy from a template).
- **What it affects:** The wording every client policy starts from.
- **What I need from you:** Read them and tell me what to change.
- **My recommendation / default:** Not urgent; clients will not see Compliance for a while.

### Review the mobile app plan and say what to keep  `r7-ai-36`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Waiting on:** Review by you  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Review the mobile app plan and say what to keep.
- **What it affects:** Whether a mobile app is built and what it does (push for critical alerts, approvals).
- **What I need from you:** Read the plan (docs) and tell me what to keep or drop.
- **My recommendation / default:** -

### Sales and Finance > Profitability and Net income: client profit by month from Halo, typed or QuickBooks costs, and the finance workbook's other sheets  `rw-profitability`
- **Area:** Sales and Finance  |  **Waiting on:** Review by you  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Profitability and Net income with their tabs. Now built: Revenue to net income, New clients, By industry, Hours, Ranking, Client summary, P&L, QBO Profitability, Historical client revenue, QBO Travel, Hardware COGS, Inputs, Settings > Finance, add-on and support software by license counts.
- **What it affects:** Finance numbers you read and decide on.
- **What I need from you:** Look at the live tabs against the workbook and tell me what is off. Also: choose the counts for each software vendor (Settings > Finance > Software costs), set the 10 agents still on the default $65 rate, and answer the Onboarding question.
- **My recommendation / default:** -

## Approval (1)

### Approve the weekly VM snapshot role command  `r7-cf-39`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Approval  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Approve the weekly VM snapshot role command (lets the deployment identity create weekly snapshots of the VMs).
- **What it affects:** Azure permissions and cost of snapshots.
- **What I need from you:** Approve the role assignment command.
- **My recommendation / default:** Approve.

## Go-ahead (1)

### Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6)  `acorn-rename`
- **Area:** Platform  |  **Waiting on:** Go-ahead  |  **Added:** 2026-11-15  |  **Status:** in progress
- **What it is:** Rename AiSOC and Jarvis to A.C.O.R.N and CORE (steps 3 to 6 of docs/RENAME_AUDIT_2026-11-15.md change names other things depend on: folders, package names, container names, URLs).
- **What it affects:** Almost everything: builds, deploy scripts, the VM, links. Needs a window when you are away.
- **What I need from you:** Your go-ahead, one step at a time, and tell me when you are away.
- **My recommendation / default:** Do it in one planned weekend window.

## Access and decision (1)

### Google Workspace BEC: full mailbox scan  `google-bec-scan`
- **Area:** Security  |  **Waiting on:** Access and decision  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A full Google Workspace mailbox scan for business email compromise. ThreatMate cannot read mailboxes and the light Google check is on hold.
- **What it affects:** Client Google Workspace mailboxes: reads mail, so a privacy and consent matter.
- **What I need from you:** Grant a service account domain-wide delegation with Gmail read scope (or Google Vault export) per client, and say which clients first. Without it nothing can be built.
- **My recommendation / default:** Start with one friendly client to prove it.

## Question (2)

### Liongard: turn the disk and backup inspections into per-device lines with names  `r7-cf-11`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Question  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Liongard: turn the disk and backup inspections into per-device lines with names. Liongard alerts already name the affected disks and devices (the Datto backup check lists each system and days since the last backup).
- **What it affects:** Devices page, alerts and Client posture for Liongard-flagged items.
- **What I need from you:** What is missing: (a) a row on the Devices page for each flagged device, (b) one alert per device instead of one per client, or (c) device names on the Client posture checks?
- **My recommendation / default:** (c) first, it is the smallest.

### Net income: an Onboarding section (the workbook's Onboarding tab)  `finance-onboarding-tab`
- **Area:** Finance  |  **Waiting on:** Question  |  **Added:** 2026-11-18  |  **Status:** new
- **What it is:** The workbook's Onboarding tab is a list of time entries on onboarding projects (773 rows from April 2026: user, role, customer, project, phase, task, effort, tracked time, billable, category, notes, approved).
- **What it affects:** A possible new Net income section: onboarding hours and labor cost per client.
- **What I need from you:** Which system exports it (HaloPSA projects or another tool), and what the section should show (hours and cost per client, by phase?).
- **My recommendation / default:** Once the source is known CORE can read it.

## Questions (1)

### Employee toolbox (from Rewst Tool Portal): client picker and Microsoft 365 action tiles  `rw-toolbox`
- **Area:** Security  |  **Waiting on:** Questions  |  **Added:** 2026-11-15  |  **Status:** not started
- **What it is:** Employee toolbox (from the Rewst Tool Portal): a client picker and Microsoft 365 action tiles (reset MFA, change password, remediation, out of office, mailbox permissions and more) as a launcher over CIPP actions with the approval path.
- **What it affects:** Real changes to client Microsoft 365 accounts; highest-risk item on the list.
- **What I need from you:** Which actions first, who may press them, whether every press needs approval, whether the user picker lists A.C.O.R.N identities, and whether scheduled workflows wait.
- **My recommendation / default:** Five tiles (reset MFA, change password, compromised-user remediation, out of office, mailbox permissions); every press creates an approval request.

## Decision (27)

### Audits: auditor sign-in and a data room (the audit tracker is built)  `audits-data-room`
- **Area:** Compliance  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The audit tracker is built (audits with evidence requests, owners, due dates, provided and accepted). Still missing: a sign-in for the external auditor and a place to keep the evidence files.
- **What it affects:** Compliance > Audits. Adds a new kind of user (auditor) and file storage (where evidence files live: cost, retention, who can read them).
- **What I need from you:** Does the auditor get their own sign-in limited to one audit? Where should the files be stored (A.C.O.R.N database, Azure storage, or stay as links to files elsewhere)?
- **My recommendation / default:** Auditor gets a read-only role limited to one audit; files kept in Azure blob storage per audit with a retention date. I can build this once you agree. See also r7-af-16 and r7-af-17, which are the same work split in two.

### Trust center: a public share link (the signed-in trust center is built)  `trust-center`
- **Area:** Compliance  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** in progress
- **What it is:** The trust center page exists behind sign-in. A public link would let a prospect or customer view it without signing in.
- **What it affects:** Compliance > Trust center. A public address means anyone with the link can read what you choose to publish (policies, certifications, documents).
- **What I need from you:** Do you want a public link at all? If yes: one per client, which documents may be shown, and a switch to turn it off.
- **My recommendation / default:** One public link per client, off by default, with an off switch and a list of exactly which documents are shown. See also r7-af-18.

### Compliance in the client-facing part of A.C.O.R.N  `client-facing-compliance`
- **Area:** Compliance  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Show the Compliance section to your clients in their own sign-in, after it works for Live Oak.
- **What it affects:** What clients can see about their own compliance; needs the client sign-in (client_viewer role) already built for the customer dashboard.
- **What I need from you:** Who sees what: which compliance pages, read-only or editable, and whether all clients or chosen ones.
- **My recommendation / default:** Read-only compliance overview and policies for clients you choose, using the existing client sign-in with the authenticator app. See also r7-af-35 and r7-af-37.

### Parent and child clients (families) so New Waterloo and its NW - clients share group records  `huntress-family`
- **Area:** Devices  |  **Waiting on:** Decision (held at your request)  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Parent and child clients (families), e.g. New Waterloo and its NW - clients, so group-level records follow to the child client when tools file same-named machines under siblings.
- **What it affects:** Devices, Huntress and every other tool's records for the family; also the ThreatMate zeros on Billing sync for the NW - locations.
- **What I need from you:** Your go-ahead to design families (it is held until you say). It also decides how a merge across clients is allowed (see merge-search-sibling).
- **My recommendation / default:** Start with a read-only family link (parent to children) used for reporting and counts before any record moves between clients.

### Follow a machine by name alone when it has a random Windows default name  `name-only-follow`
- **Area:** Devices  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** Follow a machine by name alone when Windows gave it a random default name (so a rename or re-image does not look like a new device).
- **What it affects:** Device identity and merging across tools; could wrongly join two machines that share a name.
- **What I need from you:** Whether following by name alone is acceptable, and under what condition (same client only?).
- **My recommendation / default:** Only within one client and only when the serial number is missing. Held with the families design.

### Device merge search that finds a machine filed under a sibling client  `merge-search-sibling`
- **Area:** Devices  |  **Waiting on:** Decision (held with families)  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** The device merge search would also find a machine filed under a sibling client.
- **What it affects:** A merge across clients moves a record between clients, so it touches client data boundaries.
- **What I need from you:** Decide together with huntress-family.
- **My recommendation / default:** Do not build until families are decided.

### NinjaOne command console (CMD and PowerShell)  `ninja-console`
- **Area:** Devices  |  **Waiting on:** Decision (on hold at your request)  |  **Added:** 2026-11-14  |  **Status:** not started
- **What it is:** A NinjaOne command console (CMD and PowerShell) inside A.C.O.R.N.
- **What it affects:** Remote command execution on client machines: a high-risk capability; needs the approval path and audit.
- **What I need from you:** Your go-ahead and the rules (who, which clients, approval on every command?).
- **My recommendation / default:** Keep on hold.

### Move secrets from the .env file into the Windows credential store  `r7-ci-15`
- **Area:** Round 7: CORE improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Move secrets (API keys and tokens) from CORE's .env file into the Windows credential store.
- **What it affects:** How CORE starts and how updates work; secrets would no longer sit in a text file. Risk: a mistake could stop CORE from reading its keys.
- **What I need from you:** Whether to do it, and whether the VM may be restarted during the change.
- **My recommendation / default:** Worth doing; I would do it as an option that falls back to .env.

### Merge the duplicated connector descriptions into one source  `r7-ci-33`
- **Area:** Round 7: CORE improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Merge the duplicated connector descriptions (they live in more than one place) into one source.
- **What it affects:** CORE connectors list, docs and A.C.O.R.N connector cards; a refactor with no visible change.
- **What I need from you:** Go-ahead (low risk, internal).
- **My recommendation / default:** Yes.

### Rename the old aisoc-* files to acorn-* in one reviewed batch  `r7-ci-38`
- **Area:** Round 7: CORE improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Rename the old aisoc-* files to acorn-* in one reviewed batch.
- **What it affects:** Many file names and imports in CORE and A.C.O.R.N; risk of breaking builds and old links.
- **What I need from you:** Go-ahead, and the moment (it should happen when you are away; see acorn-rename).
- **My recommendation / default:** Do it with acorn-rename steps 3 to 6 in one planned window.

### Detected applications also from Google Workspace  `r7-ai-34`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Detected applications (SaaS apps found in use) also from Google Workspace, not only Microsoft.
- **What it affects:** Compliance > Vendors detected applications; needs Google Workspace access like google-bec-scan.
- **What I need from you:** Whether to build it and whether you will grant read access to Google Workspace app/OAuth data.
- **My recommendation / default:** Build after the Google access decision.

### A per-client switch that requires single sign-on  `r7-ai-35`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A per-client switch that requires single sign-on (Microsoft) for that client's users.
- **What it affects:** Sign-in for that client's users; wrongly set it can lock them out.
- **What I need from you:** Which clients first, and whether password sign-in stays as a fallback for admins.
- **My recommendation / default:** Opt-in per client with an admin fallback.

### Decide how long audit logs are kept by default  `r7-ai-40`
- **Area:** Round 7: A.C.O.R.N improvement  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Decide how long audit logs are kept by default.
- **What it affects:** Storage and what you can prove later; compliance frameworks often expect 12 months.
- **What I need from you:** A retention period (for example 12 or 24 months) and whether clients may choose their own.
- **My recommendation / default:** 12 months online, longer archived.

### HaloPSA: ticket-to-alert round trip: closing the ticket resolves the alert  `r7-cf-17`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** HaloPSA ticket to alert round trip: closing the ticket in Halo resolves the alert in A.C.O.R.N.
- **What it affects:** Alert status, and what your technicians see in Halo; risk of closing a real alert because a ticket was closed.
- **What I need from you:** Whether closing a ticket may resolve the alert automatically, for which alert types.
- **My recommendation / default:** Only when every alert in the case is already handled.

### HaloPSA: create a ticket for a failing automated control test  `r7-cf-18`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** HaloPSA: create a ticket for a failing automated control test.
- **What it affects:** Ticket volume in Halo; needs a ticket type and priority.
- **What I need from you:** Whether to do it, for which client and what ticket type and priority.
- **My recommendation / default:** One ticket per failing test per client, deduplicated.

### Slack: post the morning summary of new critical alerts to a channel  `r7-cf-19`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Slack: post the morning summary of new critical alerts to a channel.
- **What it affects:** Posts content from client alerts into a Slack channel (who is in it matters).
- **What I need from you:** Whether to do it, the channel, the time and whether client names may appear.
- **My recommendation / default:** A private channel, 8:00, client names included.

### Windows: start with the machine as a service option  `r7-cf-30`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Windows: start CORE with the machine as a service option.
- **What it affects:** How CORE runs on the VM and restarts; permissions and auto-update behaviour.
- **What I need from you:** Go-ahead.
- **My recommendation / default:** Yes, as a service with auto-restart.

### A first-run wizard that checks each connector and says what is missing  `r7-cf-37`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A first-run wizard that checks each connector and says what is missing.
- **What it affects:** Setup experience for a new install; no change to existing ones.
- **What I need from you:** Go-ahead.
- **My recommendation / default:** Yes.

### Add a second CORE VM for failover  `r7-cf-40`
- **Area:** Round 7: CORE feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Add a second CORE VM for failover.
- **What it affects:** Azure cost (a second VM) and complexity: two CORE copies must not both act.
- **What I need from you:** Whether the extra cost and complexity are wanted.
- **My recommendation / default:** Not yet; the snapshots cover recovery.

### Vendors: a questionnaire sent to the vendor as a form with a link  `r7-af-06`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Vendors: send a questionnaire to the vendor as a form with a link they fill in.
- **What it affects:** A public form (no sign-in) that outside parties fill; what vendor data is stored.
- **What I need from you:** Go-ahead and the questions to ask (or use the built-in questionnaire).
- **My recommendation / default:** Link expires after 30 days; answers saved to the vendor record.

### Policies: a staff acceptance page with a link per person  `r7-af-13`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Policies: a staff acceptance page with a link per person (each employee confirms they read a policy).
- **What it affects:** A public page per person; evidence of acceptance for audits.
- **What I need from you:** Go-ahead and whether e-mail sending is allowed (see policy reminders).
- **My recommendation / default:** Yes, with one-time links.

### Audits: a read-only auditor view limited to one audit  `r7-af-16`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Audits: a read-only auditor view limited to one audit.
- **What it affects:** A new sign-in type; same as audits-data-room.
- **What I need from you:** Decide with audits-data-room.
- **My recommendation / default:** -

### Audits: a data room of uploaded files per audit  `r7-af-17`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Audits: a data room of uploaded files per audit.
- **What it affects:** File storage; same as audits-data-room.
- **What I need from you:** Decide with audits-data-room.
- **My recommendation / default:** -

### Trust center: a public share link with an off switch  `r7-af-18`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Trust center: a public share link with an off switch.
- **What it affects:** Same as trust-center.
- **What I need from you:** Decide with trust-center.
- **My recommendation / default:** -

### Settings: an export and import of settings between organizations  `r7-af-34`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Settings: export and import of settings between organizations.
- **What it affects:** Copying settings from one organization or client to another; risk of copying secrets or wrong rules.
- **What I need from you:** Which settings may be copied (never secrets) and whether needed.
- **My recommendation / default:** Rules and frameworks only.

### Roles: a role for read-only compliance viewers  `r7-af-35`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** Roles: a role for read-only compliance viewers.
- **What it affects:** Adds a role that sees compliance pages only.
- **What I need from you:** Go-ahead and the exact pages.
- **My recommendation / default:** Yes.

### A client-facing portal with only the compliance pages  `r7-af-37`
- **Area:** Round 7: A.C.O.R.N feature  |  **Waiting on:** Decision  |  **Added:** 2026-11-14  |  **Status:** new
- **What it is:** A client-facing portal with only the compliance pages.
- **What it affects:** Same as client-facing-compliance.
- **What I need from you:** Decide with client-facing-compliance.
- **My recommendation / default:** -
