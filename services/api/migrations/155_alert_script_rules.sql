-- Migration 155: run a script automatically for an alert type, choosing the script by the machine's operating system.
--
-- alert_script_rules: one row per "when an alert of this type appears for a machine, run this script on it" decision, owned by the tenant that made it (the MSSP). `scope` is client or all; `client_tenant_id`
-- names the client for a client rule. `signature` is the alert type (as for alert_ticket_rules) and `source` the tool that raised it. `windows_script_id` and `mac_script_id` are the ids of scripts CORE
-- published as switched on (either may be empty: a machine of that kind is then left alone). `requires_tool` optionally names a tool (a device source such as 'screenconnect') the client must already have
-- on at least one machine, so a rule never acts for a client that does not use it. `revoked_at` is set when a person turns the rule off.
--
-- A.C.O.R.N runs nothing itself: for each covered alert it queues the same "run_script" request the alert page's Run script button does (vendor 'core'); CORE decides whether to ask its owner first
-- (a script switched to "run at once" there starts straight away, any other waits for an approval card). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS alert_script_rules (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    scope             VARCHAR(10)  NOT NULL CHECK (scope IN ('client', 'all')),
    client_tenant_id  UUID         REFERENCES tenants (id) ON DELETE CASCADE,
    source            VARCHAR(100),
    signature         TEXT         NOT NULL,
    title             TEXT         NOT NULL DEFAULT '',
    windows_script_id INTEGER,
    mac_script_id     INTEGER,
    requires_tool     VARCHAR(40),
    created_by        UUID,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ,
    CHECK (windows_script_id IS NOT NULL OR mac_script_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_alert_script_rules_tenant_active ON alert_script_rules (tenant_id) WHERE revoked_at IS NULL;

ALTER TABLE alert_script_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON alert_script_rules;
CREATE POLICY tenant_isolation ON alert_script_rules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
