-- Migration 159: authenticator-app codes (TOTP) for the password sign-in (improvement A13).
--
-- user_totp: one row per person who has started setting up an authenticator app. `secret_enc` is the TOTP secret encrypted with the credential vault (never stored in the clear). `confirmed_at` is set when the person
-- proved they can read codes from the app; until then the row changes nothing about signing in. `last_used_step` is the 30-second step of the last accepted code, so a code cannot be used twice. `recovery_hashes`
-- holds SHA-256 hashes of the single-use recovery codes that remain. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS user_totp (
    user_id         UUID         PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    tenant_id       UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    secret_enc      TEXT         NOT NULL,
    confirmed_at    TIMESTAMPTZ,
    last_used_step  BIGINT,
    recovery_hashes JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_totp_tenant ON user_totp (tenant_id);

ALTER TABLE user_totp ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON user_totp;
CREATE POLICY tenant_isolation ON user_totp
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
