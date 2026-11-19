-- Migration 223: auditor access to one audit, and the files kept for an audit (Compliance > Audits).
--
-- audit_auditors links a user with the auditor role to the audits they may open: an auditor sees nothing else. audit_files holds the evidence files an audit collects, uploaded by staff or by the auditor,
-- kept in the database (so the nightly backup covers them) with a size limit enforced by the API. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS audit_auditors (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    audit_id    UUID         NOT NULL REFERENCES audits (id) ON DELETE CASCADE,
    user_id     UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_by  VARCHAR(320),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_id, user_id)
);
CREATE INDEX IF NOT EXISTS audit_auditors_user_idx ON audit_auditors (user_id);

CREATE TABLE IF NOT EXISTS audit_files (
    id              UUID         PRIMARY KEY,
    tenant_id       UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    audit_id        UUID         NOT NULL REFERENCES audits (id) ON DELETE CASCADE,
    request_id      UUID         REFERENCES audit_requests (id) ON DELETE SET NULL,
    name            VARCHAR(255) NOT NULL,
    content_type    VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes      INTEGER      NOT NULL CHECK (size_bytes >= 0),
    content         BYTEA        NOT NULL,
    uploaded_by     VARCHAR(320),
    by_auditor      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_files_audit_idx ON audit_files (audit_id, created_at);

ALTER TABLE audit_auditors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audit_auditors;
CREATE POLICY tenant_isolation ON audit_auditors
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE audit_files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audit_files;
CREATE POLICY tenant_isolation ON audit_files
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
