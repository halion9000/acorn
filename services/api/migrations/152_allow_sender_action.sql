-- Migration 152: an "allow_sender" action for CORE: put one sender address on the tenant allow list.
--
-- A person decides on a "user asked to release a quarantined message" alert that the sender should be allowed; A.C.O.R.N queues "allow_sender" (the vendor_actions queue, vendor 'core') and CORE has CIPP add the one
-- address to the tenant allow list with the option Microsoft calls "remove after 45 days of no use". The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender'));

COMMIT;
