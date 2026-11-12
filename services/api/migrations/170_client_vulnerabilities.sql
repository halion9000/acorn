-- Migration 170: one row per vulnerability a tool finds at a client.
--
-- client_vulnerabilities: what the Vulnerabilities page lists line by line. Until now a tool's findings arrived only as one check ("440 critical and 4798 high vulnerabilities in 37 programs")
-- and one alert built from it, which says how many and never which. CORE now also sends the list itself: one entry per vulnerability and program (a CVE in one version of one program), with
-- how serious it is, whether an exploit is known and which of the client's machines have it. Each daily list replaces the last for that client and tool (snapshot_id); first_seen is kept
-- from the first time the entry was listed. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_vulnerabilities (
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source        VARCHAR(40)   NOT NULL,
    cve_id        VARCHAR(60)   NOT NULL,
    software      VARCHAR(200)  NOT NULL,
    version       VARCHAR(100)  NOT NULL DEFAULT '',
    severity      VARCHAR(10)   NOT NULL,
    cvss          REAL,
    exploited     BOOLEAN       NOT NULL DEFAULT FALSE,
    devices       INTEGER       NOT NULL DEFAULT 0,
    device_names  TEXT          NOT NULL DEFAULT '',
    first_seen    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    snapshot_id   UUID          NOT NULL,
    PRIMARY KEY (tenant_id, source, cve_id, software, version),
    CONSTRAINT client_vulnerabilities_severity CHECK (severity IN ('critical', 'high', 'medium', 'low'))
);

CREATE INDEX IF NOT EXISTS idx_client_vulnerabilities_rank ON client_vulnerabilities (tenant_id, severity, exploited, devices);

ALTER TABLE client_vulnerabilities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_vulnerabilities;
CREATE POLICY tenant_isolation ON client_vulnerabilities
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
