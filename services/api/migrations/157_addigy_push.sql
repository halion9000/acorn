-- Migration 157: push a tool to a Mac through Addigy ("addigy_push" action) and let an automatic-install rule do it.
--
-- A rule with via_addigy set also asks CORE to re-run the Addigy policy deployment on Macs that only Addigy manages and that lack the tool, after CORE checks that the Mac's Addigy policy
-- (its own and its parents) really installs it. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push'));

ALTER TABLE tool_deploy_rules ADD COLUMN IF NOT EXISTS via_addigy boolean NOT NULL DEFAULT false;

-- A rule needs a script for some kind of machine OR the Addigy push (migration 156 required a script).
ALTER TABLE tool_deploy_rules DROP CONSTRAINT IF EXISTS tool_deploy_rules_check;
ALTER TABLE tool_deploy_rules DROP CONSTRAINT IF EXISTS tool_deploy_rules_has_a_way;
ALTER TABLE tool_deploy_rules ADD CONSTRAINT tool_deploy_rules_has_a_way
    CHECK (windows_script_id IS NOT NULL OR mac_script_id IS NOT NULL OR via_addigy);

COMMIT;
