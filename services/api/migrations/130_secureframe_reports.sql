-- secureframe_reports: the latest report CORE sends from Secureframe (compliance automation): how many control tests are enabled, passing, failing and not evaluated, the failing and passing tests per framework,
-- the oldest failing tests with their owner, and how many risks and policies exist. One row per organization, replaced by each report. Read only here. No credential, policy text or evidence is ever in it.
BEGIN;

CREATE TABLE IF NOT EXISTS secureframe_reports (
    tenant_id   UUID        PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    report      JSONB       NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE secureframe_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON secureframe_reports;
CREATE POLICY tenant_isolation ON secureframe_reports
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
