-- Migration 108: a target check score for each client.
--
-- client_score_targets: the score (0-100) a client should stay at or above, set by a person. Owned by the account that owns the feed (tenant_id), one row per client (client_id); the fleet page marks a
-- client whose score is below its target. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_score_targets (
    tenant_id  UUID        NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_id  UUID        NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    target     SMALLINT    NOT NULL CHECK (target BETWEEN 1 AND 100),
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, client_id)
);

ALTER TABLE client_score_targets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_score_targets;
CREATE POLICY tenant_isolation ON client_score_targets
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
