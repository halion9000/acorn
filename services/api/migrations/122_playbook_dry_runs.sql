-- playbook_dry_runs: "this playbook WOULD have run for this alert, with these steps". The first form of automatic playbooks records and shows what would happen and takes NO action; full
-- automation comes later, per playbook, after these have been reviewed. One row per alert per playbook. Safe to run again.
BEGIN;

CREATE TABLE IF NOT EXISTS playbook_dry_runs (
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    alert_id      UUID         NOT NULL,
    playbook_id   VARCHAR(120) NOT NULL,
    playbook_name VARCHAR(255) NOT NULL,
    matched_on    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    steps         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, alert_id, playbook_id)
);

CREATE INDEX IF NOT EXISTS idx_playbook_dry_runs_recent ON playbook_dry_runs (tenant_id, created_at DESC);

ALTER TABLE playbook_dry_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON playbook_dry_runs;
CREATE POLICY tenant_isolation ON playbook_dry_runs
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
