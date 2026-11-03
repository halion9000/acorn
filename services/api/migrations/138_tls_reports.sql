-- Migration 138: TLS reports (TLS-RPT, RFC 8460): the daily JSON a receiving mail server sends about how many TLS-protected connections to a client's mail servers worked or failed, and why.
--
-- tls_reports: one row per policy in a report (a report can speak of the same domain under more than one policy type). tenant_id is the client the domain belongs to, matched the same way as
-- DMARC reports (migration 136), or the owner's own tenant with matched = false. A policy of a report is stored once however many times the report is read. `failures` holds the failure kinds
-- and their session counts, e.g. [{"type": "certificate-expired", "count": 3}].
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS tls_reports (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    matched     BOOLEAN       NOT NULL DEFAULT TRUE,
    domain      VARCHAR(255)  NOT NULL,
    reporter    VARCHAR(200)  NOT NULL DEFAULT '',
    report_id   VARCHAR(255)  NOT NULL,
    policy_type VARCHAR(30)   NOT NULL DEFAULT 'unknown',
    begin_at    TIMESTAMPTZ   NOT NULL,
    end_at      TIMESTAMPTZ   NOT NULL,
    success     INTEGER       NOT NULL DEFAULT 0,
    failure     INTEGER       NOT NULL DEFAULT 0,
    failures    JSONB         NOT NULL DEFAULT '[]'::jsonb,
    received_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tls_reports_once ON tls_reports (domain, reporter, report_id, policy_type);
CREATE INDEX IF NOT EXISTS ix_tls_reports_tenant_end ON tls_reports (tenant_id, end_at DESC);

ALTER TABLE tls_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tls_reports;
CREATE POLICY tenant_isolation ON tls_reports
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
