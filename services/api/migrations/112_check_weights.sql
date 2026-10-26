-- Migration 112: how much each check counts towards a client's score.
--
-- check_weights: a weight from 1 to 5 for a check key (default 1 for every check not listed), set by a person and applied to every client's score: a check of weight 3 moves the score three times as
-- much as one of weight 1. Owned by the account that owns the feed (tenant_id). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS check_weights (
    tenant_id  UUID        NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key        VARCHAR(80) NOT NULL,
    weight     SMALLINT    NOT NULL CHECK (weight BETWEEN 1 AND 5),
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

ALTER TABLE check_weights ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON check_weights;
CREATE POLICY tenant_isolation ON check_weights
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
