-- Migration 168: the proposal log (autonomy plan, foundation 1).
--
-- agent_proposals: one row for every action an agent proposes or takes, with the rung of the autonomy ladder it landed on (shadow = "would have done", nothing happened; suggest; ask; act_tell; act_quiet), the
-- evidence it rests on (a list of {label, url}; a proposal with none is refused by the API), and what a person did with it. approval_id links the card when the proposal was asked as an approval. Kept under the
-- client's tenant. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS agent_proposals (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    agent         VARCHAR(120) NOT NULL,
    action_type   VARCHAR(80)  NOT NULL,
    target        VARCHAR(300) NOT NULL DEFAULT '',
    summary       TEXT         NOT NULL,
    rung          VARCHAR(16)  NOT NULL,
    evidence      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    confidence    DOUBLE PRECISION,
    approval_id   UUID         REFERENCES agent_approvals (id) ON DELETE SET NULL,
    outcome       VARCHAR(16)  NOT NULL DEFAULT 'none',
    outcome_note  TEXT,
    outcome_by    UUID,
    outcome_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT agent_proposals_rung_ck CHECK (rung IN ('shadow', 'suggest', 'ask', 'act_tell', 'act_quiet')),
    CONSTRAINT agent_proposals_outcome_ck CHECK (outcome IN ('none', 'accepted', 'edited', 'rejected', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_agent_proposals_tenant_created ON agent_proposals (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_proposals_type ON agent_proposals (tenant_id, action_type);

ALTER TABLE agent_proposals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_proposals;
CREATE POLICY tenant_isolation ON agent_proposals
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
