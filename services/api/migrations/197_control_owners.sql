-- Migration 197: who owns each control (roadmap r7-ai-33).
--
-- One row per client, framework and control: the person (a name or an email, free text up to 120 characters) answerable for that control. A control with no row has no owner.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS compliance_control_owners (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    framework   TEXT         NOT NULL,
    control_id  TEXT         NOT NULL,
    owner       TEXT         NOT NULL CHECK (char_length(owner) BETWEEN 1 AND 120),
    set_by      TEXT,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, framework, control_id)
);

ALTER TABLE compliance_control_owners ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON compliance_control_owners;
CREATE POLICY tenant_isolation ON compliance_control_owners
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
