-- Migration 104: what each tool counts for each client (licences bought, devices managed, people covered), and every change to those counts.
--
-- client_license_counts: the latest count per client, tool (``source`` is the tool's own name, e.g. ninjaone, cipp, datto-saas) and item ("Windows workstations", "Microsoft 365 Business Premium").
-- ``available`` is, for a licence, how many are not assigned to anyone. CORE sends these once a day with each client's checks.
--
-- client_license_history: one row each time an item first appears for a client, its count changes, or it disappears (count 0), with the count it had before. Together with the latest counts this gives the
-- count at any past date and the log of changes, which is what a bill is checked against.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_license_counts (
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source        VARCHAR(40)  NOT NULL,
    item          VARCHAR(80)  NOT NULL,
    unit          VARCHAR(12)  NOT NULL DEFAULT 'other',
    count         INTEGER      NOT NULL CHECK (count >= 0),
    available     INTEGER      CHECK (available IS NULL OR available >= 0),
    first_seen_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source, item)
);

CREATE TABLE IF NOT EXISTS client_license_history (
    id             BIGSERIAL    PRIMARY KEY,
    tenant_id      UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source         VARCHAR(40)  NOT NULL,
    item           VARCHAR(80)  NOT NULL,
    unit           VARCHAR(12)  NOT NULL DEFAULT 'other',
    count          INTEGER      NOT NULL CHECK (count >= 0),
    previous_count INTEGER      CHECK (previous_count IS NULL OR previous_count >= 0),
    observed_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_client_license_history_tenant_item ON client_license_history (tenant_id, source, item, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_client_license_history_tenant_time ON client_license_history (tenant_id, observed_at DESC);

ALTER TABLE client_license_counts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_license_counts;
CREATE POLICY tenant_isolation ON client_license_counts
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE client_license_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_license_history;
CREATE POLICY tenant_isolation ON client_license_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
