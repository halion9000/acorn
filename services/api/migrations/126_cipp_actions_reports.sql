-- cipp_actions_reports: the latest report CORE sends about the actions it can take in client Microsoft 365 tenants through CIPP: whether real actions are switched on, which clients are opted in, how many accounts are
-- protected, the action allowlist with each action's risk, and the last hundred requests with their outcome (executed, dry run, refused, failed). One row per organization, replaced by each report. Read only here: A.C.O.R.N
-- cannot change any of it (the rules are CORE's saved settings). No secret is ever in it.
BEGIN;

CREATE TABLE IF NOT EXISTS cipp_actions_reports (
    tenant_id   UUID        PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    report      JSONB       NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE cipp_actions_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON cipp_actions_reports;
CREATE POLICY tenant_isolation ON cipp_actions_reports
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
