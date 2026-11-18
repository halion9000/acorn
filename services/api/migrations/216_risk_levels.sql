-- Migration 216: the levels of each risk over time (Risk register, Heat map).
--
-- One row each time a risk is added, its likelihood or impact (before or after treatment) changes, or it is archived or brought back: the levels it had from then on and whether it counted. The heat map for any date is the newest
-- row of each risk on or before that date. Risks that existed before this migration get one row with the levels they have now, dated when they were added: the history before today is therefore approximate, and from today it is exact.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS risk_register_levels (
    id                   UUID         PRIMARY KEY,
    tenant_id            UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    risk_id              UUID         NOT NULL REFERENCES risk_register_items (id) ON DELETE CASCADE,
    at                   TIMESTAMPTZ  NOT NULL,
    likelihood           SMALLINT     NOT NULL,
    impact               SMALLINT     NOT NULL,
    residual_likelihood  SMALLINT,
    residual_impact      SMALLINT,
    active               BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS risk_register_levels_risk_idx ON risk_register_levels (tenant_id, risk_id, at);

INSERT INTO risk_register_levels (id, tenant_id, risk_id, at, likelihood, impact, residual_likelihood, residual_impact, active)
SELECT gen_random_uuid(), i.tenant_id, i.id, i.created_at, i.likelihood, i.impact, i.residual_likelihood, i.residual_impact, TRUE
FROM risk_register_items i
WHERE NOT EXISTS (SELECT 1 FROM risk_register_levels l WHERE l.risk_id = i.id);

INSERT INTO risk_register_levels (id, tenant_id, risk_id, at, likelihood, impact, residual_likelihood, residual_impact, active)
SELECT gen_random_uuid(), i.tenant_id, i.id, COALESCE(i.archived_at, i.updated_at), i.likelihood, i.impact, i.residual_likelihood, i.residual_impact, FALSE
FROM risk_register_items i
WHERE i.status = 'archived'
  AND NOT EXISTS (SELECT 1 FROM risk_register_levels l WHERE l.risk_id = i.id AND l.active = FALSE);

ALTER TABLE risk_register_levels ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_register_levels;
CREATE POLICY tenant_isolation ON risk_register_levels
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
