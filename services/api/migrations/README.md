# Migrations

SQL files applied in name order, twice by design: Postgres applies them when the database is first created, and the API's migration runner applies them again at every start (none is recorded yet). **Every file must therefore be safe to run twice** (`IF NOT EXISTS`, `DROP ... IF EXISTS` before `ADD`, `ON CONFLICT`). `tests/test_api_migrations_rerun_postgres.py` checks this for every file.

New tables with a `tenant_id` get the standard isolation policy (copy any of 095 to 097) and row-level security switched on. `tests/test_db_rls_and_grants_postgres.py` fails when a table created from 083 on does not, or when the application role (`aisoc_app`) cannot use it.

## Adding a value to a limited column

Several columns accept only a fixed list (a `CHECK (col IN (...))`). Writing a value the list does not hold fails at the database, and a test that uses a mock database will not notice. This is how the Run script button nearly shipped broken: migration 084 allowed three actions, the feature wrote a fourth, and only a real-database test caught it (fixed by 098).

To add a value:
1. Write a migration that drops the old constraint (`DROP CONSTRAINT IF EXISTS <name>`) and adds the wider one (see `098_vendor_actions_run_script.sql`).
2. Add the value to the contract in `tests/test_db_constraint_contract_postgres.py`. That test lists, for each limited column, the values the code can write (taken from the code's own constants where it has them) and checks the migrated database allows each. It fails if you add the value in code and skip the migration.

Audit of every value-limiting constraint added since 080 (2026-10-23): each column below was checked against the code that writes it; all agree.

| Table.column | Allowed (after the latest migration) | Written by |
|---|---|---|
| `client_aliases.match_source` | manual, suggested (083) | the client mapping routes |
| `vendor_actions.action` | approve, reject, resolve, run_script (084, widened by 098) | the vendor action and Run script routes |
| `vendor_actions.status` | pending, claimed, done, failed (084) | the CORE claim and result routes |
| `connector_run_log.status` | ok, warning, error (086) | the status CORE reports (limited to the same three in the request model) |
| `client_vcio_proposals.status` | suggested, approved, rejected, sent, failed, cleared (096) | the suggestion, decision and CORE result routes |
| `client_vcio_proposals.kind` | recommendation, risk (096) | the suggestion builder |
| `saved_views.view_type` | alerts, cases, investigations, playbooks (037), devices (135) | the saved-views routes |

## What 094 to 098 are for

| File | Adds |
|---|---|
| `094_identity_secure_scores.sql` | The Microsoft Secure Score per client, read through CIPP |
| `095_client_vcio_reviews.sql` | Each client's vCIO Toolbox recommendations and risks (a daily summary from CORE) |
| `096_client_vcio_proposals.sql` | What A.C.O.R.N suggests adding to a client's vCIO Toolbox, and what a person decided |
| `097_client_m365_checks.sql` | Each client's Microsoft 365 baseline checks, read through CIPP (see `docs/M365_CHECKS.md`) |
| `098_vendor_actions_run_script.sql` | Lets the vendor-actions queue carry `run_script` (the Run script button, single and bulk) |
| `135_saved_views_devices.sql` | Lets a person save named filter views on the Devices page (`saved_views.view_type` gains `devices`) |

## What 138 to 148 are for

| File | Adds |
|---|---|
| `138_tls_reports.sql` | TLS-RPT reports kept per client and domain (one row per policy) |
| `139_alert_suppression_starts_at.sql` | A start time on a hide rule, so a maintenance window can begin later |
| `140_domain_registrations.sql` | When each client domain's registration ends (RDAP lookup) |
| `141_remote_tools.sql` | Remote management and access tools found on client devices, and the owner's decision about each |
| `142_remote_tool_installs.sql` | Each install of a remote tool on a device, with the server it belongs to |
| `143_custom_remote_tools.sql` | Remote tools the owner adds to the catalog by hand |
| `144_identity_actions.sql` | Account actions on the Identities page (sign out everywhere, block, unblock) and the permission for them |
| `145_identity_merges.sql` | The owner's own merge and "not the same person" decisions on the Identities page |
| `146_bec_cases.sql` | Business email compromise searches started from the Identities page |
| `147_alert_stale.sql` | The `stale` alert status and the review of alerts nobody has touched |
| `148_identity_merges_binary_order.sql` | Fixes the order check on `identity_merges` (see below) |
| `152_allow_sender_action.sql` | One more `vendor_actions.action` value, `allow_sender` (put one sender on the tenant allow list) |
| `154_halo_user_action.sql` | One more `vendor_actions.action` value, `create_halo_user` (add a person to HaloPSA as a user) |
| `155_alert_script_rules.sql` | `alert_script_rules`: run a script automatically for an alert type, choosing the script by the machine's operating system |
| `156_tool_deploy_rules.sql` | `tool_deploy_rules`: install a tool (Huntress, Field Effect, ScreenConnect) automatically on machines that should have it and do not |
| `161_signin_state.sql` | `identity_mfa_users.signin_state` and `days_since_signin` (active / inactive 90+ / never, or unknown) from CIPP's inactive-accounts report |
| `169_inventory_checkout_permission.sql` | `inventory:checkout` added to the permissions catalog (implied by `inventory:write`; held by the technician roles), the permission for the two check-out and check-in routes |
| `160_password_never_expires.sql` | `identity_mfa_users.password_never_expires` (true / false / unknown) from CIPP's user list, for the Identities tile |
| `159_user_totp.sql` | `user_totp`: authenticator-app (TOTP) setup per person, secret encrypted, single-use recovery codes stored as hashes (A13) |
| `158_bec_followup.sql` | `bec_cases.aisoc_case_id`, `ticket_id`, `ticket_note_queued`: a BEC search started by a person opens a case and a HaloPSA ticket and writes the result on both |
| `157_addigy_push.sql` | the `addigy_push` action (re-run the Addigy policy deployment on a Mac whose policy includes the tool) and `tool_deploy_rules.via_addigy` |
| `153_inventory_write_permission.sql` | `inventory:write` added to the permissions catalog (implied by `mssp:manage`), so a custom role can manage inventory on its own |
| `151_quarantine_check_action.sql` | One more `vendor_actions.action` value, `quarantine_check` (look into why a message was quarantined, read only) |
| `150_ticket_note_action.sql` | One more `vendor_actions.action` value, `ticket_note` (a note CORE writes on HaloPSA tickets) |
| `149_alert_ticket_rules.sql` | `alert_ticket_rules` (open a HaloPSA ticket for an alert type) and two new `vendor_actions.action` values, `create_ticket` and `release_quarantine` |

### Lesson from 148: a text CHECK compares with the database's collation, not Python's

`identity_merges` stores each pair sorted (`address_a < address_b`). The code sorted with Python, which compares by character code. The database's default collation (en_US) ignores punctuation when it compares, so a pair Python called sorted could be refused by the CHECK (or the reverse), and only on a real Postgres. 148 pins the check to `COLLATE "C"`, which is byte order, the same as Python for these addresses. Any new constraint, index or ORDER BY that has to agree with Python's ordering of text needs `COLLATE "C"`, and a test on a real Postgres that compares pairs both ways (`tests/test_identity_merges_postgres.py`).
