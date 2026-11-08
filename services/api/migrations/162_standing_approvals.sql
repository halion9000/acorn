-- Migration 162: standing approvals and undo handles for agent actions.
--
-- agent_standing_approvals: one row per "always allow this KIND of action (for this client, or for all) until this date" decision a person made. A new approval card that matches an active row (not revoked,
-- not past its end date) is approved on the spot and says which standing approval did it. Only reversible kinds of action can be given one (see app/services/standing_approvals.py).
-- agent_approvals gains: standing_approval_id (which row auto-approved it), undo (how to reverse the action, a short description the agent supplies) and undone_at / undone_by_id (a person pressed Undo within 24 hours).
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS agent_standing_approvals (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    action_type  VARCHAR(80)  NOT NULL,
    client_id    VARCHAR(80),
    note         TEXT         NOT NULL DEFAULT '',
    created_by   UUID,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ  NOT NULL,
    revoked_at   TIMESTAMPTZ,
    revoked_by   UUID
);

CREATE INDEX IF NOT EXISTS idx_agent_standing_approvals_tenant ON agent_standing_approvals (tenant_id, action_type);

ALTER TABLE agent_standing_approvals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_standing_approvals;
CREATE POLICY tenant_isolation ON agent_standing_approvals
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS standing_approval_id UUID;
ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS undo JSONB;
ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS undone_at TIMESTAMPTZ;
ALTER TABLE agent_approvals ADD COLUMN IF NOT EXISTS undone_by_id UUID;

COMMIT;
