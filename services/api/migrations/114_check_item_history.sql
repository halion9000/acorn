-- Migration 114: when a machine or account joined or left the list behind a check.
--
-- client_check_item_history: one row each time an item (a machine name, an account) appears in, or disappears from, the list a tool gives for a client's check (for example the machines without antivirus).
-- Written when CORE sends the client's checks and the list differs from the last one; the first list ever seen is not a "join" of every item. Tied to the client like the other check rows.
-- Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_check_item_history (
    id          BIGSERIAL    PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key         VARCHAR(80)  NOT NULL,
    item        VARCHAR(120) NOT NULL,
    event       VARCHAR(8)   NOT NULL CHECK (event IN ('joined', 'left')),
    observed_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_client_check_item_history_tenant_key ON client_check_item_history (tenant_id, key, observed_at DESC);

ALTER TABLE client_check_item_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_check_item_history;
CREATE POLICY tenant_isolation ON client_check_item_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
