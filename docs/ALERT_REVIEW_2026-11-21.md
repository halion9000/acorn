# Alert review, 2026-11-21

What the last 60 days of alerts say about the detections, read from the live database (15,676 alerts). Numbers are exact counts from that read.

## What is in the alert queue

| Source | Alerts | Closed or resolved | Notes |
|---|---|---|---|
| Vendor tools through CORE (Huntress, NinjaOne, Blumira, Field Effect, ThreatMate, Addigy) | 12,397 | 7,935 | 1,783 marked false positive |
| CIPP identity detections (A.C.O.R.N rules in `identity_detections.py`) | 2,278 | 3 | almost none are ever closed |
| A.C.O.R.N checks (`aisoc-checks`) | 881 | 419 | Huntress coverage, patches, end of life, exposure |
| Remote tools | 117 | 108 | |

Severity: low 7,594, info 2,992, high 2,731, medium 1,979, critical 380.

## The big finding: the 199,307 detection rules never fire

The Detection Rules page holds 199,307 active rules (199,230 built in, 77 custom, all marked active) and every one has **zero hits**. The alerts do not come from them: only 3,277 of 15,676 alerts carry a rule id, and all of those are the CIPP and A.C.O.R.N check rules above. The rules need raw log events; the only things reaching A.C.O.R.N are vendor alerts and CIPP data, so the rule engine has nothing to run on. "247 techniques covered" on the coverage page therefore describes rules that cannot fire here, not detections that work.

Proposal: keep the library but show it as "library" (the same split the Controls page now has between implemented and inactive), and base the coverage page on the rules that have fired or can fire with the data that arrives (CIPP sign-ins and audit log, vendor alerts).

## Noise that hides real alerts

1. **Huntress agent checks, about 3,300 low alerts.** "Process: 'com.huntress.HuntressAgent' does not exist" (2,198), "'HuntressAgent' does not exist" (549), "'Huntress*' does not exist" (483), "software *Huntress* was not installed" (81). These are NinjaOne conditions firing per device, per day. They should roll up into one alert per client and device ("Huntress agent missing on N devices"), which the existing "Huntress protection fell below target" check (278 alerts, 90 clients, at most 12 each) already says in client terms.
2. **macOS disk space, about 2,000 low and info alerts.** Most are volumes that are full by design: iOS simulator runtimes under `/Library/Developer/CoreSimulator` (97 to 100 percent, hundreds of alerts), installer images under `/Volumes`, cryptex mounts, recovery volumes. Only the data volume is a real disk problem. Suppress by path pattern; keep `/System/Volumes/Data`.
3. **User-reported email, about 1,400.** "Reported as malware or phish" (528) should become a case with a ticket; "junk" (373) and "not junk" (68) are information and can close themselves.
4. **Old CVEs as high severity.** "Heap buffer overflow in libwebp" (50) and "CVE-2006-5051 in OpenSSH" (27) are scanner findings raised as high alerts. Gate by exploitability (known-exploited list) and age, and group by client.
5. **TLS cipher and open-port information alerts** (about 150 info).

## Identity detections that need work

1. **"Sign-in succeeded after N wrong passwords" (306 alerts) had the count in the title**, so every new success from an attacker who kept guessing was a new kind of alert (one account showed 22 different titles and 81 alerts). Fixed in this change: the count moves to the summary, and there is one alert per person, day and address signed in from. Suppression and ticket rules now work on it.
2. **"Added to a directory role - unknown" (269 high alerts)**: 256 of them are Microsoft's own "Partner Customer Delegated Admin Offline Processor" adding the MSP's administrators through a delegated admin relationship, on one client. Fixed in this change: that actor is low and says it is expected; other apps stay high, and a missing target no longer ends the title in "unknown". Still to decide: "AssistAPI" (one client, several a day) and "ThreatMate" (our own scanner) also appear as role adders; they are real apps, so they were left alone until you confirm they are expected.
3. **Consent given to an application (373 alerts, 51 clients).** 153 are "Microsoft Graph" itself and 21 "Microsoft Graph Command Line Tools". The rule treats every consent the same. It should look at the permissions granted (mail, files and offline access are the risky ones) and the publisher, and keep a short list of apps the MSP uses (Claude connectors, ChatGPT, security awareness training) as informational.
4. **Legacy-protocol sign-in (343 alerts)** is mostly scanners and copiers (xmdreports, scan@, scopier@, ricoh@, scanner@): the same few accounts every day. Raise once per account per week, and state that the fix is an app password or a relay, not an incident.
5. **Blumira's "Atypical travel" (21), "Unfamiliar sign-in properties" (54 open) and "User authentication from new country" (45)** overlap CIPP's own "Impossible travel" (35) and "Sign-in from an unusual country" (45). The same sign-in is alerted twice by two tools with different titles. Link them on user and hour so a person sees one incident.

## Rules that should have triggered, and did not

The data shows several accounts with a full attack chain where every step was a separate medium or high alert and nothing joined them:

- `pfamiglietti@pirkeybarber.com`: password guessing and a success, 22 different sign-in-after-wrong-passwords titles, then "BEC search ... CIPP rates it High" (3 times), 81 alerts since 2 November.
- `kaytlynw@gsctx.org`: sign-in after repeated wrong passwords, then a BEC search rated High.
- `bgerard@xstrememd.com`, `bpaschal@gmfirm.com`: sign-in methods deleted by an administrator, unfamiliar sign-in, outside guests invited, BEC search rated High.
- `itadmin@texasadvocacyproject.org`: device-code sign-in, consent, a credential added to an application, a Conditional Access policy changed, mass deletion of 11 users or groups and 8 guests invited, all in a few days.

None became a critical alert. Proposed new rule, **likely account takeover** (critical, one alert per person): within 24 hours, one *entry* signal (password guessed, password spray success, impossible travel, unusual country, device-code sign-in, MFA fatigue) together with one *foothold* sign (sign-in methods registered or deleted by an administrator, a credential added to an application, consent, a role added, a Conditional Access change, an inbox rule, a BEC search rated High). It uses data A.C.O.R.N already holds; it needs no new feed.

Other new rules the data supports:

- **Inbox rule that forwards or deletes** (T1114.003) and **mailbox delegation added** (T1098.002) from the CIPP audit log; only T1114 and T1098.001 appear today, so these may be partly covered. Needs a check against what CIPP sends.
- **Legacy sign-in for a person who has never used it** (not the scanner accounts above).
- **Sign-in from an anonymizer or Tor address** when the address data allows it.
- **Huntress agent gone on a device that had it yesterday** (a removed agent is T1562.001), separate from "never installed".

## Mapping to ATT&CK

13,278 of 15,676 alerts (85 percent) have no technique, so the heatmap shows only the identity detections. Cheap mappings that need only a title match: user-reported phish T1566; unfamiliar sign-in, new country and atypical travel T1078; suspicious user agents T1078; potentially unsecured credentials in files T1552.001; Microsoft Defender service stopped and Huntress agent missing T1562.001; BitLocker disabled and old operating systems have no honest technique (leave unmapped rather than guess).

## What was built

First change: two rule fixes in `identity_detections.py` (the guessed-password title and key, and the partner-service role addition).

Second change, from the same review: the **Likely account takeover** rule (`detect_takeover_chain`, one critical alert per person and day, joins the saved identity alerts after each new one), ATT&CK techniques for vendor alerts by title, and resolving by-design alerts as benign (`services/alert_triage.py`, run every minute by the suppression sweeper; each resolved alert carries an `auto_triage` note and can be reopened). Nothing was deleted.

Still proposals, not built: rolling the Huntress "does not exist" alerts into one per client and device, the consent rule by permissions and publisher, once-a-week legacy-protocol alerts, linking Blumira and CIPP sign-in alerts, gating old CVEs by exploitability, and the library-versus-active split of the 199,307 rules.
