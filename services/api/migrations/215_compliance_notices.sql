-- Migration 215: where the compliance action items are sent each week (an e-mail list and a webhook).
--
-- One row per organization or client (the scope the Compliance page is showing): who is e-mailed, an optional web address that gets the same list as JSON, and when it last went. A worker sends it at most once a week
-- and only when something is waiting. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS compliance_notices (
    tenant_id      UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    emails         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    webhook_url    TEXT,
    weekly         BOOLEAN      NOT NULL DEFAULT FALSE,
    last_sent_at   TIMESTAMPTZ,
    last_result    TEXT,
    updated_by     TEXT,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE compliance_notices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON compliance_notices;
CREATE POLICY tenant_isolation ON compliance_notices
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
