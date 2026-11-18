-- Migration 210: approval of a policy version (Policies, Request approval).
--
-- One row per request: a numbered version of a policy, the person asked to approve it, and what they decided. A version can be asked about again after it is rejected; only one request per version waits at a time.
-- The decision, who made it and when stay on file (an approval record). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS policy_approvals (
    id              UUID         PRIMARY KEY,
    tenant_id       UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id         UUID         NOT NULL REFERENCES governance_items (id) ON DELETE CASCADE,
    version         INTEGER      NOT NULL,
    approver_email  TEXT         NOT NULL,
    requested_by    TEXT         NOT NULL,
    requested_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    note            TEXT         NOT NULL DEFAULT '',
    decision        TEXT         NOT NULL DEFAULT 'pending',
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    comment         TEXT         NOT NULL DEFAULT '',
    CONSTRAINT policy_approvals_decision CHECK (decision IN ('pending', 'approved', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS policy_approvals_one_pending ON policy_approvals (item_id, version) WHERE decision = 'pending';
CREATE INDEX IF NOT EXISTS policy_approvals_item_idx ON policy_approvals (tenant_id, item_id, version);
CREATE INDEX IF NOT EXISTS policy_approvals_approver_idx ON policy_approvals (tenant_id, approver_email) WHERE decision = 'pending';

ALTER TABLE policy_approvals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON policy_approvals;
CREATE POLICY tenant_isolation ON policy_approvals
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
