-- Migration 191: client profitability (Sales and Finance).
--
-- finance_profit_snapshots: ONE row per organization, replaced each time CORE sends (about once a day): invoiced revenue per client per month, hours worked per client / agent / charge type per month,
-- and the agents, as HaloPSA holds them. A.C.O.R.N holds no HaloPSA key; CORE reads Halo and sends this. Profit is worked out when a person with the finance permissions asks, so the row holds the raw
-- summary and nothing derived.
-- finance_labor_rates: what an hour of an agent's time costs the company, set by the owner: for one agent, for a team, or one default for everyone (scope agent, team, default). The most specific
-- applies. Money in numeric, never float.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_profit_snapshots (
    tenant_id    UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    payload      JSONB        NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance_labor_rates (
    tenant_id    UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    scope        TEXT          NOT NULL,
    key          TEXT          NOT NULL DEFAULT '',
    hourly_rate  NUMERIC(10,2) NOT NULL,
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, scope, key),
    CONSTRAINT finance_labor_rates_scope CHECK (scope IN ('agent', 'team', 'default')),
    CONSTRAINT finance_labor_rates_rate CHECK (hourly_rate >= 0 AND hourly_rate <= 10000)
);

ALTER TABLE finance_profit_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_profit_snapshots;
CREATE POLICY tenant_isolation ON finance_profit_snapshots
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE finance_labor_rates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_labor_rates;
CREATE POLICY tenant_isolation ON finance_labor_rates
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
