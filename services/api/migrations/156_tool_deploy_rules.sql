-- Migration 156: install a tool automatically on machines that should have it and do not.
--
-- tool_deploy_rules: one row per "where this tool is missing, run its install script" decision, owned by the tenant that made it (the MSSP). `tool` is the tool whose coverage gap it closes (huntress,
-- fieldeffect or screenconnect), `scope` is client or all and `client_tenant_id` names the client for a client rule. `windows_script_id` and `mac_script_id` are the ids of scripts CORE published as switched on
-- (either may be empty: a machine of that kind is then left alone). `revoked_at` is set when a person turns the rule off.
--
-- A machine is "missing" the tool by the rule the Devices page already uses (a computer the client's other machines show the tool on, not one the client was marked as not using it, not one offline for long);
-- the rule also needs the client to have the tool on at least one machine. A.C.O.R.N runs nothing itself: for each such machine it queues the same "run_script" request the alert page's Run script button does
-- (vendor 'core'), and CORE decides whether to ask its owner first. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS tool_deploy_rules (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    tool              VARCHAR(40)  NOT NULL CHECK (tool IN ('huntress', 'fieldeffect', 'screenconnect')),
    scope             VARCHAR(10)  NOT NULL CHECK (scope IN ('client', 'all')),
    client_tenant_id  UUID         REFERENCES tenants (id) ON DELETE CASCADE,
    windows_script_id INTEGER,
    mac_script_id     INTEGER,
    created_by        UUID,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ,
    CHECK (windows_script_id IS NOT NULL OR mac_script_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_tool_deploy_rules_tenant_active ON tool_deploy_rules (tenant_id) WHERE revoked_at IS NULL;

ALTER TABLE tool_deploy_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tool_deploy_rules;
CREATE POLICY tenant_isolation ON tool_deploy_rules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
