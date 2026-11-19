-- Migration 230: the Toolbox can ask CORE for a client's groups and licenses and for one person's inbox rules (read only).
--
-- Two more vendor actions for vendor 'core', queued by the Toolbox forms so they offer real choices instead of a text box: 'directory_lookup' (the groups and licenses of a client's domain) and
-- 'mailbox_rules_lookup' (one person's inbox rules). CORE answers through the same result route as 'user_lookup' and result_data keeps the structured answer. Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command', 'ninja_deploy', 'halo_billing_update', 'user_lookup', 'directory_lookup', 'mailbox_rules_lookup'));

COMMIT;
