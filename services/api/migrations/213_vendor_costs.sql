-- Migration 213: what each software vendor billed (QuickBooks) and which license counts stand behind each vendor.
--
-- finance_vendor_costs: one row per month, account (5500 add-on software, 5100 support and maintenance software) and vendor, with the amount QuickBooks booked. CORE sends them; a month sent again is replaced.
-- finance_vendor_map: for a vendor, the counts (a tool and an item, such as halopsa and "Huntress EDR") that say how many licenses of it each client has. Typed by a person (seeded from finance's Software Master).
-- Together they let Net income carry each vendor's bill to the clients that use it, by license count, instead of spreading it by revenue. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_vendor_costs (
    tenant_id    UUID           NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT           NOT NULL,
    account      TEXT           NOT NULL,
    vendor       TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL,
    received_at  TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month, account, vendor),
    CONSTRAINT finance_vendor_costs_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT finance_vendor_costs_account CHECK (account IN ('5100', '5500'))
);

CREATE TABLE IF NOT EXISTS finance_vendor_map (
    tenant_id  UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor     TEXT         NOT NULL,
    source     TEXT         NOT NULL,
    item       TEXT         NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, vendor, source, item)
);

ALTER TABLE finance_vendor_costs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_vendor_costs;
CREATE POLICY tenant_isolation ON finance_vendor_costs
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE finance_vendor_map ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_vendor_map;
CREATE POLICY tenant_isolation ON finance_vendor_map
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
