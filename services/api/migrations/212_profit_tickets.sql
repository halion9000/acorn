-- Migration 212: every ticket a client's hours went on, per month (Profitability, client detail).
--
-- CORE sends the tickets of one month at a time (the summary of invoices and hours stays small over two years). One row per month holds that month's list; sending a month again replaces it. The client detail reads the rows
-- of the month it shows. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_profit_tickets (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT         NOT NULL,
    payload      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month),
    CONSTRAINT finance_profit_tickets_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$')
);

ALTER TABLE finance_profit_tickets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_profit_tickets;
CREATE POLICY tenant_isolation ON finance_profit_tickets
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
