-- Migration 161: last sign-in state per person (improvement NA8, second part).
--
-- identity_mfa_users.signin_state: 'active' (signed in within 90 days, or a brand new account), 'inactive' (last sign-in 90 or more days ago) or 'never' (an account more than 14 days old with no sign-in on record), from
-- CIPP's inactive-accounts report; NULL when the client's sign-in data is not available (CIPP only has it with Entra ID P1), which is never shown as "never signed in". days_since_signin is set when 'inactive'. Idempotent.

BEGIN;

ALTER TABLE identity_mfa_users ADD COLUMN IF NOT EXISTS signin_state varchar(12);
ALTER TABLE identity_mfa_users ADD COLUMN IF NOT EXISTS days_since_signin integer;

COMMIT;
