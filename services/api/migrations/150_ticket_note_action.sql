-- Migration 150: a "ticket_note" action for CORE: add a note to HaloPSA tickets.
--
-- When a quarantined message is released (from A.C.O.R.N, or by someone else in Microsoft 365) A.C.O.R.N queues "ticket_note" (the vendor_actions queue, vendor 'core') naming the alert's HaloPSA tickets
-- and the sentence to write; CORE adds it as a private note. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note'));

COMMIT;
