-- Migration 224: when each directory account was first seen and when it was last seen leaving or disabled (Identities > Joiners and leavers).
--
-- One row per tenant, source and account. first_seen is the day A.C.O.R.N first saw the account; baseline is true for the accounts already there the first time a source reported, whose real
-- join day is unknown (they are not shown as joiners). left_at is set when the account is disabled or no longer listed, and cleared if it comes back. Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS identity_history (
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source        VARCHAR(40)  NOT NULL,
    user_id       VARCHAR(100) NOT NULL,
    upn           VARCHAR(320) NOT NULL,
    display_name  VARCHAR(255),
    first_seen    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    baseline      BOOLEAN      NOT NULL DEFAULT FALSE,
    last_seen     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    left_at       TIMESTAMPTZ,
    snapshot_id   UUID         NOT NULL,
    PRIMARY KEY (tenant_id, source, user_id)
);
CREATE INDEX IF NOT EXISTS identity_history_first_idx ON identity_history (tenant_id, first_seen);
CREATE INDEX IF NOT EXISTS identity_history_left_idx ON identity_history (tenant_id, left_at);

ALTER TABLE identity_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON identity_history;
CREATE POLICY tenant_isolation ON identity_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
