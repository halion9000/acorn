-- Migration 140: when each client domain's registration ends (A91).
--
-- domain_registrations: one row per client and domain, the last registration lookup (RDAP) for it. expires_at is NULL when the record could not be read or carries no expiry date; `error` then says why,
-- so "could not look it up" is never shown as "fine". checked_at drives how often it is looked at again (weekly, daily within thirty days of the end, daily after a failure).
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS domain_registrations (
    tenant_id  UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    domain     VARCHAR(255)  NOT NULL,
    registered TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    checked_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    error      VARCHAR(200),
    PRIMARY KEY (tenant_id, domain)
);

ALTER TABLE domain_registrations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON domain_registrations;
CREATE POLICY tenant_isolation ON domain_registrations
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
