-- Migration 219: record the automated control tests nightly (Compliance, Automated tests).
--
-- One row per organization or client (the scope the Compliance page is showing) that switched nightly recording on: a worker then writes the results of the automated control tests as evidence, as Record now does, at most once
-- a night. The row says when it last ran and what happened. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS compliance_test_schedule (
    tenant_id    UUID         PRIMARY KEY REFERENCES tenants (id) ON DELETE CASCADE,
    nightly      BOOLEAN      NOT NULL DEFAULT FALSE,
    last_run_at  TIMESTAMPTZ,
    last_result  TEXT,
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE compliance_test_schedule ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON compliance_test_schedule;
CREATE POLICY tenant_isolation ON compliance_test_schedule
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
