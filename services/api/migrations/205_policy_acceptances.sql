-- Migration 205: who accepted which version of a policy (Policies, Acceptance).
--
-- One row per person per policy version: the person's e-mail (lower case), the day they accepted, and who recorded it. Rows are only added (a newer version asks again). Row-level security with the standard
-- policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS policy_acceptances (
    id           UUID         PRIMARY KEY,
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id      UUID         NOT NULL REFERENCES governance_items (id) ON DELETE CASCADE,
    version      INTEGER      NOT NULL,
    email        TEXT         NOT NULL,
    display_name TEXT,
    accepted_on  DATE         NOT NULL,
    recorded_by  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (item_id, version, email)
);

CREATE INDEX IF NOT EXISTS policy_acceptances_item_idx ON policy_acceptances (tenant_id, item_id, version);

ALTER TABLE policy_acceptances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON policy_acceptances;
CREATE POLICY tenant_isolation ON policy_acceptances
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
