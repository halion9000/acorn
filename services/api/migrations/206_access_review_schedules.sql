-- Migration 206: access reviews that start themselves (Access Reviews, Repeat).
--
-- One schedule per system: every N days (90 is a quarter) a review of that system's people is started with the chosen reviewer, due 30 days later. next_start is the day the next one is due to start;
-- last_error says why the last attempt started nothing (for example no people held for the system). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS access_review_schedules (
    id             UUID         PRIMARY KEY,
    tenant_id      UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    system         TEXT         NOT NULL,
    reviewer       TEXT,
    every_days     INTEGER      NOT NULL DEFAULT 90 CHECK (every_days BETWEEN 7 AND 400),
    next_start     DATE         NOT NULL,
    enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    last_review_id UUID,
    last_error     TEXT,
    created_by     TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, system)
);

CREATE INDEX IF NOT EXISTS access_review_schedules_due_idx ON access_review_schedules (next_start) WHERE enabled;

ALTER TABLE access_review_schedules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON access_review_schedules;
CREATE POLICY tenant_isolation ON access_review_schedules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
