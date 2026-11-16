-- Migration 196: metric_datasets, the weekly and monthly facts behind the Metrics pages (Staff, Tickets, Finance, Customer Insights).
--
-- One row per organization and dataset key, replaced each time CORE sends (about once a day). A.C.O.R.N holds no HaloPSA, Dialpad or CIPP key: CORE reads them and sends what the pages need, and every page is
-- worked out from these rows when a person asks (nothing is read live). Keys: staff-weekly (per engineer per week: team, hours, utilization, days off, tickets closed and updated, calls, survey scores),
-- ticket-detail (tickets created and resolved per week by client, type, category and priority, resolution time, stale tickets), invoice-lines (billed per client per month per invoice line and category),
-- dialpad-weekly (calls per engineer per week) and m365-roles (directory roles and their members per client). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS metric_datasets (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key          TEXT         NOT NULL,
    payload      JSONB        NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key),
    CONSTRAINT metric_datasets_key CHECK (key IN ('staff-weekly', 'ticket-detail', 'invoice-lines', 'dialpad-weekly', 'm365-roles'))
);

ALTER TABLE metric_datasets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON metric_datasets;
CREATE POLICY tenant_isolation ON metric_datasets
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
