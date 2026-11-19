-- Migration 231: the Toolbox can ask CORE to run a tool for a client through CIPP (action 'toolbox_run').
--
-- One more vendor action for vendor 'core': params name the tool and its values (a typed password is never queued), the client's CIPP customer id and HaloPSA client id; CORE runs it under its CIPP
-- safety rules, writes the work into the ticket and answers with the result. Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command', 'ninja_deploy', 'halo_billing_update', 'user_lookup', 'directory_lookup', 'mailbox_rules_lookup', 'toolbox_run'));

COMMIT;
