-- Migration 222: the transactions behind the travel and hardware costs in QuickBooks (Net income: QBO Travel and Hardware COGS).
--
-- finance_cost_transactions: one row per month holding every transaction filed to the travel accounts (5800, 5805) and the hardware account (5600): date, type, who it was paid to, the customer it was for, the memo, the account it
-- was paid from and the amount. CORE sends them; a month sent again is replaced. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_cost_transactions (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT         NOT NULL,
    payload      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month),
    CONSTRAINT finance_cost_transactions_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$')
);

ALTER TABLE finance_cost_transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_cost_transactions;
CREATE POLICY tenant_isolation ON finance_cost_transactions
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
