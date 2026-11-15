-- Migration 190: audits (Secureframe parity plan): an audit of a framework and the evidence requests that come with it.
--
-- audits: a name, the framework, the auditor's firm, the period it covers and where it stands (planning, fieldwork, review, complete).
-- audit_requests: one thing the auditor asks for (a title, optionally the control it is about, an owner, a due date) and where it stands (open, provided, accepted), with a note and a link to what was provided.
-- Nothing is deleted. Row-level security (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS audits (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name         VARCHAR(200)  NOT NULL,
    framework    VARCHAR(20)   NOT NULL,
    auditor      VARCHAR(200),
    period_start DATE,
    period_end   DATE,
    status       VARCHAR(12)   NOT NULL DEFAULT 'planning',
    created_by   VARCHAR(320),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT audits_status CHECK (status IN ('planning', 'fieldwork', 'review', 'complete'))
);
CREATE INDEX IF NOT EXISTS idx_audits_tenant ON audits (tenant_id, status);

CREATE TABLE IF NOT EXISTS audit_requests (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    audit_id    UUID          NOT NULL REFERENCES audits (id) ON DELETE CASCADE,
    title       VARCHAR(300)  NOT NULL,
    control_id  VARCHAR(60),
    owner       VARCHAR(200),
    due_date    DATE,
    status      VARCHAR(10)   NOT NULL DEFAULT 'open',
    note        TEXT          NOT NULL DEFAULT '',
    link        VARCHAR(1000),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT audit_requests_status CHECK (status IN ('open', 'provided', 'accepted'))
);
CREATE INDEX IF NOT EXISTS idx_audit_requests_audit ON audit_requests (audit_id, status);

ALTER TABLE audits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audits;
CREATE POLICY tenant_isolation ON audits
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE audit_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audit_requests;
CREATE POLICY tenant_isolation ON audit_requests
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
