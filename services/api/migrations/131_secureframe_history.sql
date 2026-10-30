-- secureframe_history: one row per organization per day with Secureframe's pass and fail counts as CORE last reported them that day, so the Compliance page can show how the pass rate moved.
-- The latest report itself stays in secureframe_reports. Counts only: no test names, owners, policies or evidence.
BEGIN;

CREATE TABLE IF NOT EXISTS secureframe_history (
    tenant_id UUID    NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    day       DATE    NOT NULL,
    passing   INTEGER NOT NULL,
    failing   INTEGER NOT NULL,
    risks     INTEGER,
    policies  INTEGER,
    PRIMARY KEY (tenant_id, day)
);

ALTER TABLE secureframe_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON secureframe_history;
CREATE POLICY tenant_isolation ON secureframe_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
