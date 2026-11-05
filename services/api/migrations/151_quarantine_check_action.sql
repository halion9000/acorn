-- Migration 151: a "quarantine_check" action for CORE: look into why one quarantined message was held.
--
-- A person asks on a "user asked to release a quarantined message" alert; A.C.O.R.N queues "quarantine_check" (the vendor_actions queue, vendor 'core'); CORE reads the message and its headers through CIPP
-- (read only) and reports a short plain-text result with an advice, kept in the action's result_message. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check'));

COMMIT;
