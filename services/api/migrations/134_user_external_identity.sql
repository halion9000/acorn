-- Migration 134: a person can sign in with Microsoft (Entra ID).
--
-- users.external_identity holds the permanent id of the person at the identity provider ("entra:<tenant id>:<object id>"). It is how a returning person is recognised: never by email, which the person may be able to edit.
-- Unique when set, so one Microsoft identity can belong to only one account. Idempotent.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS external_identity TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_external_identity ON users (external_identity) WHERE external_identity IS NOT NULL;

COMMIT;
