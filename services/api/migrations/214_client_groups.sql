-- Migration 214: client names filed under one Primary Name (Net income).
--
-- A client is billed and worked under more than one name in HaloPSA and QuickBooks (a company and the people behind it, or a company that was renamed). Finance's Client Master files each name under one Primary Name; Net income adds
-- their revenue, hours and costs into one client. One row per member name: the name key it is matched by, the name as written, and the Primary Name it is filed under. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_client_groups (
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    member_key    TEXT         NOT NULL,
    member_name   TEXT         NOT NULL,
    primary_name  TEXT         NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, member_key)
);

ALTER TABLE finance_client_groups ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_client_groups;
CREATE POLICY tenant_isolation ON finance_client_groups
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
