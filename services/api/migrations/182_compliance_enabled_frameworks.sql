-- Migration 182: which compliance frameworks an organization (or one of its clients) has turned on.
--
-- compliance_enabled_frameworks: one row per framework switched on for a tenant. The Compliance dashboard adds up the controls of the frameworks that are on; the Frameworks page shows all of the available
-- ones with a switch. More than one can be on. No row means off. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS compliance_enabled_frameworks (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    framework   VARCHAR(40)  NOT NULL,
    enabled_by  VARCHAR(320),
    enabled_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, framework)
);

ALTER TABLE compliance_enabled_frameworks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON compliance_enabled_frameworks;
CREATE POLICY tenant_isolation ON compliance_enabled_frameworks
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
