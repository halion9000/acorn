-- Migration 160: whether a person's Microsoft 365 password is set never to expire (improvement NA8).
--
-- identity_mfa_users.password_never_expires: true when CIPP's user list says the password policy is DisablePasswordExpiration, false when it says it is not, NULL when CIPP's list could not say (the field was not
-- read, or the person is not in it). NULL is never shown as "expires". Idempotent.

BEGIN;

ALTER TABLE identity_mfa_users ADD COLUMN IF NOT EXISTS password_never_expires boolean;

COMMIT;
