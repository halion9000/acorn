-- Migration 194: the cost inputs and the client master behind the full profitability model (Sales and Finance).
--
-- finance_cost_entries: one amount per month, category and (optional) client. Categories follow finance's workbook: payroll_cogs (the P&L's client service payroll), addon_software (per client),
-- support_software, travel, equipment, hardware, sales_marketing and overhead. A row with a client is charged to that client directly; a row with no client is spread across the month's clients by
-- revenue. `source` is 'manual' (typed on the page) or 'quickbooks' (filled by the QuickBooks sync when it is connected); the two never overwrite each other.
-- finance_client_master: industry, non-profit and the net-income target for a client (the workbook's Client Master sheet), keyed by the same name key the profitability page matches Halo by.
-- finance_settings: one row per organization (hours a person can work in a month, for utilization).
-- Money in numeric, never float. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS finance_cost_entries (
    tenant_id    UUID           NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    month        TEXT           NOT NULL,
    category     TEXT           NOT NULL,
    client_key   TEXT           NOT NULL DEFAULT '',
    client_name  TEXT           NOT NULL DEFAULT '',
    source       TEXT           NOT NULL DEFAULT 'manual',
    amount       NUMERIC(14,2)  NOT NULL,
    note         TEXT           NOT NULL DEFAULT '',
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, month, category, client_key, source),
    CONSTRAINT finance_cost_entries_month CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT finance_cost_entries_category CHECK (category IN ('payroll_cogs', 'addon_software', 'support_software', 'travel', 'equipment', 'hardware', 'sales_marketing', 'overhead')),
    CONSTRAINT finance_cost_entries_source CHECK (source IN ('manual', 'quickbooks'))
);

CREATE TABLE IF NOT EXISTS finance_client_master (
    tenant_id      UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_key     TEXT          NOT NULL,
    client_name    TEXT          NOT NULL,
    industry       TEXT          NOT NULL DEFAULT '',
    non_profit     BOOLEAN       NOT NULL DEFAULT FALSE,
    target_margin  NUMERIC(5,2),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, client_key),
    CONSTRAINT finance_client_master_target CHECK (target_margin IS NULL OR (target_margin >= -100 AND target_margin <= 100))
);

CREATE TABLE IF NOT EXISTS finance_settings (
    tenant_id                  UUID          PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    available_hours_per_month  NUMERIC(6,2)  NOT NULL DEFAULT 160,
    updated_at                 TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT finance_settings_hours CHECK (available_hours_per_month > 0 AND available_hours_per_month <= 744)
);

ALTER TABLE finance_cost_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_cost_entries;
CREATE POLICY tenant_isolation ON finance_cost_entries
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE finance_client_master ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_client_master;
CREATE POLICY tenant_isolation ON finance_client_master
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE finance_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON finance_settings;
CREATE POLICY tenant_isolation ON finance_settings
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
