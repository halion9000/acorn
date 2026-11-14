# Secureframe parity for clients: gap list and build order (2026-11-14)

Source: Hal's eight screenshots of Secureframe (Tests, Controls, Policies, Risk management, Vendors, Vendor details, Vendor security reviews, Vendor documentation) and the left menu visible in all of them.
Goal (Hal, 2026-11-13 and again 2026-11-14): A.C.O.R.N does for each client what Secureframe does, without Secureframe behind it. Live Oak keeps Secureframe for itself.

## What the left menu has, and what A.C.O.R.N has today

| Secureframe area | What it is | A.C.O.R.N today | Gap |
| --- | --- | --- | --- |
| Home / Get Started (88%) | readiness score and onboarding checklist | Compliance page coverage per framework | one readiness score per client with a checklist of what is left |
| Integrations | connectors that feed tests | CORE connectors, check history | none to build; tests must use them |
| Compliance > Tests | 163 enabled tests, Passing / Failing / At risk, owner, vendor, next due, interval, "last uploaded", custom tests, test library, activity | read-only mirror of Live Oak's Secureframe tests (SecureframeCard); client posture checks (Met / Partly / Not met) | tests as first-class records per client: owner, due date, interval, upload evidence, custom tests, activity log; our own checks become tests |
| Compliance > Controls | 156 controls, Healthy / Unhealthy / At risk / Not tested, owner, description, mapped frameworks | mirror of Secureframe controls; framework requirement pages | controls per client, each linking tests and framework requirements, health rolled up from tests |
| Compliance > Frameworks | SOC 2, ISO, HIPAA, CIS IG1, NIST CSF 2.0 | framework pages with requirement list and evidence; NIST coverage | map controls to requirements for every framework we offer; readiness per framework |
| Compliance > Audits | audit periods, auditor access | none | audit records, evidence request list, auditor read-only view |
| Compliance > Data Room | documents shared with an auditor or a prospect | none | folder of documents with access links that expire |
| Governance > Policies | 44 policies, Published / Draft / Archived, owner, acceptance rate (32 of 41), groups, mapped frameworks | mirror shows name and acceptance only | policy library with templates, versions, publish, assign to groups, acceptance tracking, reminders |
| Governance > Personnel | people, onboarding status, training, policy acceptance | Identities page (accounts, MFA, devices) | the person record joined to identity: role, start and end date, groups, training, acceptance, background check |
| Governance > Access | who has access to which system, reviews | Identities page shows accounts per tool | periodic access review: list, approve, remove, evidence |
| Governance > Asset Inventory | devices, software, cloud | Devices and Inventory pages | tag an asset with owner and data classification |
| Risk > Risk Management | register with 6 risks, Dashboard / Register / Archive, inherent and residual score, treatment, tasks, risk library | Client Risk Score (vCIO questionnaire), mirror of Secureframe's register | native register: risk, category, owner, inherent score, treatment (mitigate, accept, transfer, avoid), residual score, tasks, history, library of common risks, dashboard, archive |
| Risk > Vendors | 61 vendors, risk score, review status, owner, documents, 49 detected applications | none (the word "vendor" in A.C.O.R.N means a security tool) | vendor register, detected applications from Microsoft 365 enterprise apps, risk level, recurring security reviews, documents (SOC reports), tasks, history |
| Risk > Vulnerabilities | findings list | Vulnerabilities page | already there; link to risks |
| Trust > Trust Center | public page of a client's security posture | none | per-client page, opt in, what is shown is chosen by the client |
| Trust > Questionnaires | answer security questionnaires from stored answers | cyber-insurance pre-filler idea (C62), not built | answer library and AI draft with "verified" or "needs a human" per answer |
| Trust > Knowledge Base | approved answers | none | the same answer library |
| Ask Secureframe AI | assistant over the compliance data | Leafy | give Leafy read access to the compliance records once they exist |

## Build order (each step shippable alone, each tested, each with a user guide bullet)

1. **Risk register** (no outside dependency). Tables, endpoints, page with Dashboard / Register / Archive, scoring matrix, treatment, tasks, history. Seed library of common MSP-client risks.
2. **Vendors**: register, risk level, documents, recurring reviews and tasks, detected applications from Microsoft 365 enterprise apps (CIPP already reads them).
3. **Policies**: templates, versions, publish, groups, acceptance (the person must be a Personnel record), reminders by email.
4. **Personnel and Access reviews**: the person record on top of Identities; quarterly access review with sign-off.
5. **Tests and Controls engine**: our existing checks become tests with owner, interval, due date; controls roll tests up; custom tests with evidence upload.
6. **Framework mapping and readiness score** across SOC 2, ISO 27001, HIPAA, CIS IG1, NIST CSF 2.0 (the NIST/CIS requirement catalog already exists in A.C.O.R.N).
7. **Audits and Data Room**.
8. **Trust Center, Questionnaires and Knowledge Base**.

## Questions only Hal can answer

1. Each client gets its own workspace (all lists filtered by the client picker)? Assumed yes.
2. Policy text: write 40 or so templates ourselves (CIS IG1 and NIST CSF 2.0 wording), or import Live Oak's current Secureframe policies as the starting set (needs the text, which the Secureframe read deliberately never fetches)?
3. Which frameworks first for clients? Screenshots show CIS IG1 and NIST CSF 2.0 on tests. SOC 2 and HIPAA are already on the Compliance page.
4. Trust Center: public link per client, or sign-in only?
5. Audits: will an outside auditor need to sign in, or does Live Oak export a package for them?
6. Who may edit: technicians only, or the client's own people too (policy acceptance needs the client's people)?
