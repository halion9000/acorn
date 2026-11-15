-- Migration 192: ticket statistics from HaloPSA (the ticket metrics page).
--
-- ticket_stats_snapshots: ONE row per organization, replaced each time CORE sends (about once a day): per HaloPSA client per month how many tickets were created and resolved, the first-response minutes,
-- tickets by type and by the agent who resolved them, and what is open now. A.C.O.R.N holds no HaloPSA key and no tickets for this: CORE reads Halo and sends the summary. Averages are worked out when
-- a person asks, so the row holds the raw counts and nothing derived. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS ticket_stats_snapshots (
    tenant_id    UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    payload      JSONB        NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- csat_snapshots: ONE row per organization, replaced each time CORE sends (about once a day): SimpleSat's customer satisfaction responses summed per company per month (positive, neutral, negative) and each
-- company's newest comments. The comments and contact names are customers' own words and names: they are read only with the report permission.
CREATE TABLE IF NOT EXISTS csat_snapshots (
    tenant_id    UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    payload      JSONB        NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE ticket_stats_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ticket_stats_snapshots;
CREATE POLICY tenant_isolation ON ticket_stats_snapshots
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE csat_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON csat_snapshots;
CREATE POLICY tenant_isolation ON csat_snapshots
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
