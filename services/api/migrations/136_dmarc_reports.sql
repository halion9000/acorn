-- Migration 136: DMARC aggregate reports (the daily XML mail receivers send about mail claiming to be from a client's domain), kept per client.
--
-- dmarc_reports: one row per report. tenant_id is the client the domain belongs to (matched from the e-mail domains of the client's people); when no client could be matched it is the
-- owner's own tenant with matched = false, so nothing is lost and a person can see what is waiting to be matched. A report is stored once: the same reporter's same report id for the
-- same domain is the same report however many times it is read. `rows` holds the per-source lines of the report (capped when stored); the totals are columns so lists and trends need
-- no unpacking.
--
-- dmarc_ingest_state: where the mailbox reader got to for each owner (the newest message it has read, when it last ran, what it last failed with, and counts), so the page can say
-- whether reports are flowing.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS dmarc_reports (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    matched     BOOLEAN       NOT NULL DEFAULT TRUE,
    domain      VARCHAR(255)  NOT NULL,
    reporter    VARCHAR(200)  NOT NULL DEFAULT '',
    report_id   VARCHAR(255)  NOT NULL,
    begin_at    TIMESTAMPTZ   NOT NULL,
    end_at      TIMESTAMPTZ   NOT NULL,
    policy      VARCHAR(20)   NOT NULL DEFAULT 'none',
    total       INTEGER       NOT NULL DEFAULT 0,
    passed      INTEGER       NOT NULL DEFAULT 0,
    failed      INTEGER       NOT NULL DEFAULT 0,
    rows        JSONB         NOT NULL DEFAULT '[]'::jsonb,
    received_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dmarc_reports_once ON dmarc_reports (domain, reporter, report_id);
CREATE INDEX IF NOT EXISTS ix_dmarc_reports_tenant_end ON dmarc_reports (tenant_id, end_at DESC);

CREATE TABLE IF NOT EXISTS dmarc_ingest_state (
    tenant_id   UUID          PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    cursor      TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_error  TEXT,
    stored      INTEGER       NOT NULL DEFAULT 0,
    rejected    INTEGER       NOT NULL DEFAULT 0
);

ALTER TABLE dmarc_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON dmarc_reports;
CREATE POLICY tenant_isolation ON dmarc_reports
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE dmarc_ingest_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON dmarc_ingest_state;
CREATE POLICY tenant_isolation ON dmarc_ingest_state
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
