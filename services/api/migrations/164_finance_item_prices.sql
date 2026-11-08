-- Migration 164: what each invoice line is sold for and what it costs, so an estimated margin per client can be worked out.
--
-- finance_item_prices: one row per invoice line (the HaloPSA recurring-invoice item name, as billed), owned by the MSSP: unit_price is what a client pays per unit, unit_cost what it costs per unit. The margin
-- page multiplies these by the quantity each client is billed for (the HaloPSA counts already held). Only people holding the `finance:view` / `finance:write` permissions can read or change them: prices and
-- margins are not shown to everyone who can read the licence counts. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_item_prices (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    invoice_item  VARCHAR(120)  NOT NULL,
    unit_price    NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    unit_cost     NUMERIC(12,2) NOT NULL CHECK (unit_cost >= 0),
    updated_by    UUID,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, invoice_item)
);

ALTER TABLE finance_item_prices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_item_prices;
CREATE POLICY tenant_isolation ON finance_item_prices
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
