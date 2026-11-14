-- Migration 178: the latest HaloPSA money snapshot CORE sent.
--
-- finance_halo_snapshots: ONE row per organisation, replaced each time CORE sends (about once a day): the recurring invoices with their lines (quantity, unit price, unit cost) and the invoices still
-- owed (amount due, due date), as HaloPSA holds them. A.C.O.R.N holds no HaloPSA key; CORE reads Halo and sends this. Margin and ageing are worked out from it when a person with the finance
-- permissions asks, so the row holds the raw snapshot and nothing derived. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_halo_snapshots (
    tenant_id    UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    payload      JSONB        NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE finance_halo_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_halo_snapshots;
CREATE POLICY tenant_isolation ON finance_halo_snapshots
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
