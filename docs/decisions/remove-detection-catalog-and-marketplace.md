# Plan: remove the Detection Catalog and the Marketplace

Status: DONE (2026-10-28). Hal delegated the decisions ("do what you think is best"). Step 1 (rule packs) shipped first; steps 2 to 5 followed in one pass: step 2 needed no work because the Playbooks page already lists the shared library of the 62 shipped playbooks (the agents service serves them), so nothing was moved; the pages, routes, models, seeding, tests and the two tables are removed. What is left on purpose: the static content index the Coverage page reads, and the public marketing pages' wording about a marketplace (copy for Hal to decide).

## What exists today (three separate things that look like one)

| Thing | What it is | Where | Live use |
|---|---|---|---|
| **Marketplace** (`/marketplace`) | A browse-and-"install" page over a static index of the folders `detections/`, `playbooks/` and `plugins/` in this repository. "Install" writes a row saying the tenant enabled the item. | `endpoints/marketplace.py` (452 lines), `MarketplaceView.tsx`, table `marketplace_installs` | 1 install row on the live database |
| **Community catalog** (`/community/*`) | A database store of submitted plugins, detections and playbooks with review, ratings and install counts. | `endpoints/community.py` (677 lines), `services/community_catalog.py`, table `community_catalog_items`, `DetectionCatalog.tsx` (page `/detection/catalog`), the Community tab in `PlaybooksView.tsx`, `ContributorLeaderboard.tsx` | 77 rows, all loaded by us from the shipped Sigma folder; 0 installed by anyone (0 rules in any tenant came from it) |
| **Detection Catalog page** | The browse page over the community catalog's detections. Install copies one Sigma rule into the tenant's rules in "testing" status. | `DetectionCatalog.tsx` | none |

What the content really is: 1,087 shipped detection rules (non-quarantined) and 62 playbook files in the repository, plus a `plugins/` folder of connector definitions. The catalog and the marketplace are ways of browsing files we already ship. Nobody outside this MSP submits anything, so the submit, review, rating and leaderboard parts have no users.

## What we keep (this is "grab what we need")

1. **The shipped rules.** They stay in the repository. First-party AiSOC-format rules already load as built-in rules (870 per tenant on the live stack). The 77 imported Sigma rules are what the catalog offered; they move to the Rules page instead (step 1).
2. **The playbook files.** They stay in the repository and appear on the Playbooks page itself (step 2), not behind a second store.
3. **Plugins / connectors.** Out of scope: the connector picker already covers them. The catalog could not install plugins at all (it only recorded a hash).

## Steps (each is its own commit, tested, and can be stopped after)

1. **The Sigma imports become rule packs (Hal's decision: "buckets" applied to different tenants).** The API already has rule packs (`/mssp/rule-packs`, tables `mssp_rule_packs`, `mssp_rule_pack_rules`, `mssp_rule_pack_assignments`): a parent-curated bundle of rules that is assigned to client tenants, with per-client overrides. Nothing uses it yet (0 packs) and the web app has no page for it. Plan: (a) load the 77 imported rules once, as the parent's own rules in "testing" status, instead of copying them into every client (so no 77 x 224 rows); (b) one pack per category (cloud, endpoint, identity...); (c) a Rule packs page (a tab on the Rules page): the packs with their rules, and a checkbox per client to apply a pack; (d) assigning a pack to a client is what makes its rules apply there. Open points to check in the code before building: how `resolve_effective_rules` treats a rule whose status is "testing" when its pack is assigned, and whether an assignment should also be what promotes it. Verify: assign one pack to one test client and see only that client's effective rules grow.
2. **Playbooks page lists the shipped playbook files.** Move what the Marketplace Playbooks tab and the Community tab do (browse, "add to my playbooks") into the Playbooks page. Verify: each shipped playbook appears once; adding one creates the tenant playbook.
3. **Remove the pages and menu entries.** Delete `/detection/catalog`, `/marketplace`, the Community tab, `ContributorLeaderboard`, their tests and sidebar entries; `/marketplace` and `/detection/catalog` redirect to the Rules and Playbooks pages. Verify: web build and tests, the nav tests.
4. **Remove the API.** Delete `community.py`, `marketplace.py`, `community_catalog.py`, the catalog seeding (`load_catalog_detections.py`, `seed_shipped_detections.py`, its startup task in `main.py`), their routes from `router.py`, `unguarded_routes.txt` and the route-sweep lists; regenerate the capabilities and OpenAPI docs and Cipher's copy. Verify: the full API test run, the route-sweep tests, OpenAPI check.
5. **Drop the data last, separately.** A migration drops `community_catalog_items` and `marketplace_installs` only after steps 1-4 have run on the live stack for a while. Take a copy of the 1 marketplace install row first.

## Risks and what I do not know

- Marketplace "install" of a detection only records a row. I have not confirmed whether anything reads it to turn a rule on; step 4 must grep for readers before deleting the table.
- Tenants that installed items from the catalog keep those rules (they are ordinary rules with `provenance.source = community`); removing the catalog does not remove them.
- The public benchmark page's `CommunitySubmissions` component is a different feature and is not touched.
- Roles that hide `/marketplace` or `/detection/catalog` in their saved settings will point at pages that no longer exist; harmless, but the role editor should drop them.

## Decided by Hal

- Sigma rules: buckets (packs) applied to tenants, not copied into every client.
- Roles & Permissions moved under Settings (done, 2026-10-28).

## Still needs Hal's decision

1. Are any of the 62 playbooks you would not want shown on the Playbooks page?
2. Do all five steps in order, or stop after step 3 (pages gone, API and tables left in place for now)?
