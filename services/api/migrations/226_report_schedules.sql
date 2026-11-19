-- Migration 226: scheduled reports (Reports > Executive digest > Scheduled reports): choose a report, who gets it and how often.
-- One row per schedule. frequency is daily, weekly (day = weekday 0 Monday to 6 Sunday) or monthly (day = 1 to 28); the hour is UTC. Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS report_schedules (
    id             UUID          PRIMARY KEY,
    tenant_id      UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name           VARCHAR(120)  NOT NULL,
    report_kind    VARCHAR(40)   NOT NULL,
    emails         TEXT[]        NOT NULL DEFAULT '{}',
    frequency      VARCHAR(8)    NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    day            SMALLINT      NOT NULL DEFAULT 0,
    hour_utc       SMALLINT      NOT NULL DEFAULT 7 CHECK (hour_utc BETWEEN 0 AND 23),
    enabled        BOOLEAN       NOT NULL DEFAULT TRUE,
    last_run_at    TIMESTAMPTZ,
    last_result    VARCHAR(300),
    created_by     VARCHAR(320),
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS report_schedules_tenant_idx ON report_schedules (tenant_id);

ALTER TABLE report_schedules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON report_schedules;
CREATE POLICY tenant_isolation ON report_schedules
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
