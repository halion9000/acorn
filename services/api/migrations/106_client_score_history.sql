-- Migration 106: a client's check score, once a day, so a score has a history and not only its checks.
--
-- client_score_history: one row per client per day (the last report of the day wins): the score (the share of the client's checks that are fine, accepted ones left out; NULL when it has no checks) and
-- how many checks were met, partly met, not met and accepted. Written when CORE sends a client's checks (see apply_m365_checks). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_score_history (
    tenant_id UUID        NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    day       DATE        NOT NULL,
    score     SMALLINT,
    met       INTEGER     NOT NULL DEFAULT 0,
    partly    INTEGER     NOT NULL DEFAULT 0,
    not_met   INTEGER     NOT NULL DEFAULT 0,
    accepted  INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, day)
);

ALTER TABLE client_score_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_score_history;
CREATE POLICY tenant_isolation ON client_score_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
