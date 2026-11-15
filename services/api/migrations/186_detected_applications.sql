-- Migration 186: detected applications (Secureframe parity plan: the vendor page's "Detected applications").
--
-- CORE reads each client's Microsoft 365 tenant through CIPP (the apps people consented to) and reports them. One row per tenant and application: its name, how many consents there are (accounts), the scopes
-- it holds, whether any scope is a risky one, when it was first and last seen. A person decides each one: Add (makes it a vendor), Ignore (hides it) or Link (joins it to a vendor that is already there, so
-- several apps of one vendor show as one). status: new, added, linked, ignored. Nothing is deleted. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS detected_applications (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source      VARCHAR(40)   NOT NULL,
    app_id      VARCHAR(200)  NOT NULL,
    name        VARCHAR(300)  NOT NULL,
    accounts    INTEGER       NOT NULL DEFAULT 0,
    scopes      JSONB         NOT NULL DEFAULT '[]'::jsonb,
    risky       BOOLEAN       NOT NULL DEFAULT false,
    first_seen  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    status      VARCHAR(10)   NOT NULL DEFAULT 'new',
    vendor_id   UUID          REFERENCES vendors (id) ON DELETE SET NULL,
    actioned_by VARCHAR(320),
    actioned_at TIMESTAMPTZ,
    CONSTRAINT detected_applications_status CHECK (status IN ('new', 'added', 'linked', 'ignored')),
    CONSTRAINT detected_applications_unique UNIQUE (tenant_id, source, app_id)
);

CREATE INDEX IF NOT EXISTS idx_detected_applications_tenant ON detected_applications (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_detected_applications_vendor ON detected_applications (vendor_id);

ALTER TABLE detected_applications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON detected_applications;
CREATE POLICY tenant_isolation ON detected_applications
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
