-- Migration 207: policies assigned to people (Policies, Assign).
--
-- One row per person per policy: who must accept the policy, by when, and how often they have been reminded. A person has accepted when policy_acceptances holds their e-mail for the newest version.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS policy_assignments (
    id               UUID         PRIMARY KEY,
    tenant_id        UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id          UUID         NOT NULL REFERENCES governance_items (id) ON DELETE CASCADE,
    email            TEXT         NOT NULL,
    display_name     TEXT,
    due_on           DATE         NOT NULL,
    assigned_by      TEXT,
    assigned_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_reminded_at TIMESTAMPTZ,
    reminders_sent   INTEGER      NOT NULL DEFAULT 0,
    UNIQUE (item_id, email)
);

CREATE INDEX IF NOT EXISTS policy_assignments_item_idx ON policy_assignments (tenant_id, item_id);
CREATE INDEX IF NOT EXISTS policy_assignments_email_idx ON policy_assignments (tenant_id, email);

ALTER TABLE policy_assignments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON policy_assignments;
CREATE POLICY tenant_isolation ON policy_assignments
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
