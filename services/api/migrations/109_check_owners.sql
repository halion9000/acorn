-- Migration 109: who is looking after a failing check for a client, and by when.
--
-- client_check_owners: one row per client and check (key): a person's name (free text, up to 80 characters) and an optional due date. Tied to the client like the accepted-risk rows. The fleet boards and
-- the client page show the owner and mark a check overdue once its due date has passed and it is still not met or partly met. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_check_owners (
    tenant_id  UUID        NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key        VARCHAR(80) NOT NULL,
    owner      VARCHAR(80) NOT NULL,
    due_date   DATE,
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

ALTER TABLE client_check_owners ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_check_owners;
CREATE POLICY tenant_isolation ON client_check_owners
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
