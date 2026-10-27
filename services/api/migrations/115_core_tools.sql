-- 115: the tools connected in CORE, as CORE reports them, so A.C.O.R.N can list them as connected.
--
-- CORE holds the credentials for the owner's tools (Huntress, NinjaOne, Petra...). It tells A.C.O.R.N which of them are set up, once a pass, and A.C.O.R.N shows each as connected on the Connectors
-- page. Nothing about a credential is sent: only the tool's id, name, one line about it and whether it is connected. Each report replaces the last. Safe to run twice.

BEGIN;

CREATE TABLE IF NOT EXISTS core_tools (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    tool_id     VARCHAR(60)  NOT NULL,
    title       VARCHAR(120) NOT NULL,
    description VARCHAR(300) NOT NULL DEFAULT '',
    connected   BOOLEAN      NOT NULL DEFAULT FALSE,
    reported_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tool_id)
);

ALTER TABLE core_tools ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON core_tools;
CREATE POLICY tenant_isolation ON core_tools
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
