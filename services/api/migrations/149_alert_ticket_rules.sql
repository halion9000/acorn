-- Migration 149: open a HaloPSA ticket automatically for an alert type.
--
-- alert_ticket_rules: one row per "make a ticket for this alert type" decision, owned by the tenant that made it (the MSSP). `scope` is client or all; `client_tenant_id` names the client for a client rule.
-- `signature` is the alert type (`rule:<rule id>` when the alert carries a rule, else `title:<title>`, as for alert_suppressions) and `source` the tool that raised it. `revoked_at` is set when a person
-- turns the rule off. A rule only covers alerts raised after it was made (and the alert it was made from).
--
-- A.C.O.R.N opens nothing itself: for each matching alert without a ticket it queues a "create_ticket" action for CORE (the vendor_actions queue, vendor 'core'), CORE opens the ticket in HaloPSA and
-- reports its number, which is then linked to the alert. The same migration allows "release_quarantine": a person asks A.C.O.R.N to release a quarantined message and CORE has CIPP do it
-- (services/quarantine_release.py). The action check is widened here (see tests/test_db_constraint_contract_postgres.py).
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine'));

CREATE TABLE IF NOT EXISTS alert_ticket_rules (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    scope            VARCHAR(10)  NOT NULL CHECK (scope IN ('client', 'all')),
    client_tenant_id UUID         REFERENCES tenants (id) ON DELETE CASCADE,
    source           VARCHAR(100),
    signature        TEXT         NOT NULL,
    title            TEXT         NOT NULL DEFAULT '',
    created_by       UUID,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    revoked_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alert_ticket_rules_tenant_active ON alert_ticket_rules (tenant_id) WHERE revoked_at IS NULL;

ALTER TABLE alert_ticket_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON alert_ticket_rules;
CREATE POLICY tenant_isolation ON alert_ticket_rules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
