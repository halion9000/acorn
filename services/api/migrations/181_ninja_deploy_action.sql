-- Migration 181: install the NinjaOne agent on a machine through ScreenConnect ("ninja_deploy" action), from the Devices page.
--
-- A.C.O.R.N holds no NinjaOne or ScreenConnect key: the request is queued for CORE (vendor 'core'), which makes the installer link, sends the install command, waits for the machine to appear in
-- NinjaOne and sets its role. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command', 'ninja_deploy'));

COMMIT;
