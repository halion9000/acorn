-- Migration 225: saved remote scripts (reboot, flush DNS, gpupdate...) that people with the scripts:run permission can send to machines through ScreenConnect.
-- One row per script: a name, the command text and whether it is switched on. Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS remote_scripts (
    id          UUID          PRIMARY KEY,
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name        VARCHAR(80)   NOT NULL,
    command     VARCHAR(1000) NOT NULL,
    enabled     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_by  VARCHAR(320),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS remote_scripts_name_idx ON remote_scripts (tenant_id, lower(name));

ALTER TABLE remote_scripts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON remote_scripts;
CREATE POLICY tenant_isolation ON remote_scripts
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
