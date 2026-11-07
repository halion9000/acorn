-- Migration 154: a "create_halo_user" action for CORE: add one person to HaloPSA as a user of a client.
--
-- A person presses "Add to HaloPSA" on an identity that has a cloud account and no HaloPSA user; A.C.O.R.N queues "create_halo_user" (the vendor_actions queue, vendor 'core') and CORE creates the user under
-- the client's main site in HaloPSA and reports the outcome. The action check is widened here (see tests/test_db_constraint_contract_postgres.py). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user'));

COMMIT;
