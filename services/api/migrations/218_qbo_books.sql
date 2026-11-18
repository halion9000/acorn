-- Migration 218: QuickBooks' profit and loss lines, its sales by customer, and the way customers are grouped into clients (Net income: P&L, QBO Profitability, Historical client revenue).
--
-- finance_pnl_months: one row per month holding the profit and loss as QuickBooks shows it, line by line (depth, kind header / line / total, label, amount). CORE sends them; a month sent again is replaced.
-- finance_qbo_sales: one row per month holding what each QuickBooks customer was invoiced that month (accrual). CORE sends them; a month sent again is replaced.
-- A QuickBooks customer is counted under the client its name is filed under in the client groups (Settings > Finance); a customer not filed is its own client.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_pnl_months (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT         NOT NULL,
    payload      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month),
    CONSTRAINT finance_pnl_months_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$')
);

CREATE TABLE IF NOT EXISTS finance_qbo_sales (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT         NOT NULL,
    payload      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month),
    CONSTRAINT finance_qbo_sales_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$')
);

ALTER TABLE finance_pnl_months ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_pnl_months;
CREATE POLICY tenant_isolation ON finance_pnl_months
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE finance_qbo_sales ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_qbo_sales;
CREATE POLICY tenant_isolation ON finance_qbo_sales
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
