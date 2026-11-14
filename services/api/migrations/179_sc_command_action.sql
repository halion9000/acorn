-- Migration 179: send a command to a machine through ScreenConnect ("sc_command" action), from the command prompt on the Devices page.
--
-- A.C.O.R.N runs nothing and holds no ScreenConnect secret: the request is queued for CORE (vendor 'core'), CORE sends the command through the RESTful API Manager extension and reports the
-- machine's answer as the result. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command'));

COMMIT;
