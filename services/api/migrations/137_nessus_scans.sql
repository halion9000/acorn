-- Migration 137: uploaded Tenable Nessus scans (.nessus exports), kept per client.
--
-- nessus_scans: one row per upload. tenant_id is the client the scan is about (or the owner's own tenant for the company's own network). The counts are columns so a list needs no unpacking.
-- nessus_findings: one row per finding on a host (informational findings are not kept: they describe the host, they are not a problem). device_id is the machine in the device list the host was
-- matched to by name or address, when exactly one matched; NULL otherwise ("not in inventory").
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS nessus_scans (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name           VARCHAR(200)  NOT NULL DEFAULT '',
    description    VARCHAR(300),
    notes          TEXT,
    scan_type      VARCHAR(8)    NOT NULL DEFAULT 'other' CHECK (scan_type IN ('lan', 'wan', 'other')),
    uploaded_by    VARCHAR(320),
    uploaded_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    hosts          INTEGER       NOT NULL DEFAULT 0,
    matched_hosts  INTEGER       NOT NULL DEFAULT 0,
    critical       INTEGER       NOT NULL DEFAULT 0,
    high           INTEGER       NOT NULL DEFAULT 0,
    medium         INTEGER       NOT NULL DEFAULT 0,
    low            INTEGER       NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_nessus_scans_tenant ON nessus_scans (tenant_id, uploaded_at DESC);

CREATE TABLE IF NOT EXISTS nessus_findings (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id     UUID          NOT NULL REFERENCES nessus_scans (id) ON DELETE CASCADE,
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    host_name   VARCHAR(255)  NOT NULL,
    host_ip     VARCHAR(64),
    host_fqdn   VARCHAR(255),
    host_os     VARCHAR(255),
    device_id   UUID,
    plugin_id   VARCHAR(40)   NOT NULL DEFAULT '',
    name        VARCHAR(300)  NOT NULL,
    severity    SMALLINT      NOT NULL CHECK (severity BETWEEN 1 AND 4),
    port        INTEGER       NOT NULL DEFAULT 0,
    protocol    VARCHAR(10)   NOT NULL DEFAULT '',
    service     VARCHAR(60)   NOT NULL DEFAULT '',
    cvss        REAL,
    cves        JSONB         NOT NULL DEFAULT '[]'::jsonb,
    exploit     BOOLEAN       NOT NULL DEFAULT FALSE,
    synopsis    VARCHAR(500)  NOT NULL DEFAULT '',
    solution    VARCHAR(1000) NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_nessus_findings_scan ON nessus_findings (scan_id, severity DESC);
CREATE INDEX IF NOT EXISTS ix_nessus_findings_device ON nessus_findings (device_id) WHERE device_id IS NOT NULL;

ALTER TABLE nessus_scans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nessus_scans;
CREATE POLICY tenant_isolation ON nessus_scans
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE nessus_findings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nessus_findings;
CREATE POLICY tenant_isolation ON nessus_findings
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
