-- Migration 208: Leafy can ask CORE to look a person up (the 'user_lookup' vendor action).
--
-- A.C.O.R.N holds no CIPP, Huntress or Intune keys: CORE does. The Copilot (Leafy) queues a 'user_lookup' for CORE (vendor 'core', like every other request A.C.O.R.N hands to CORE), CORE reads the person's
-- sign-ins, audit events, multi-factor setup, mailbox rules and devices (reads only) and answers with a short text and the structured result. result_data keeps that structured answer. Idempotent.

BEGIN;

ALTER TABLE vendor_actions ADD COLUMN IF NOT EXISTS result_data JSONB;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command', 'ninja_deploy', 'halo_billing_update', 'user_lookup'));

COMMIT;
