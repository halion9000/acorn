-- Migration 204: an in-app announcement banner a person can post for the team (Settings, Announcements).
--
-- A short message with a tone (info or warning) and an optional end day, shown above every page to everyone in the organization until it ends or is removed. Row-level security with the standard policy
-- (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS announcements (
    id          UUID         PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    message     TEXT         NOT NULL,
    tone        TEXT         NOT NULL DEFAULT 'info' CHECK (tone IN ('info', 'warning')),
    ends_on     DATE,
    created_by  TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS announcements_tenant_idx ON announcements (tenant_id, created_at DESC);

ALTER TABLE announcements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON announcements;
CREATE POLICY tenant_isolation ON announcements
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
