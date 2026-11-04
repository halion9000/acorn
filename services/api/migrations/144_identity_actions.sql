-- Migration 144: account actions on the Identities page (sign a person out everywhere, block or unblock their sign-in) and the permission that allows them.
--
-- The actions use the queue that already exists between A.C.O.R.N and CORE (vendor_actions, migration 084): A.C.O.R.N writes a pending row for vendor 'core', CORE collects it, carries it out through
-- CIPP (CORE holds the credentials; A.C.O.R.N never does) and reports done or failed. Two changes make the queue fit:
--   * alert_id may be empty: an account action starts from a person, not from an alert;
--   * the allowed actions grow by revoke_sessions, disable_user and enable_user.
-- The permission identities:respond is not implied by any other, so only an administrator ("*") and a custom role that ticks it can use the buttons. Idempotent.

BEGIN;

ALTER TABLE vendor_actions ALTER COLUMN alert_id DROP NOT NULL;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user'));

INSERT INTO permissions (name, description, category) VALUES
    ('identities:respond', 'Sign a person out of Microsoft 365 everywhere, or block and unblock their sign-in, from the Identities page (carried out by CORE through CIPP, for opted-in clients only)', 'identities')
ON CONFLICT (name) DO NOTHING;

COMMIT;
