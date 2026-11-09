-- Migration 166: notes on an alert that change nothing about it.
--
-- alert_notes: a short note a person writes on an alert (what they looked at, who they called) without changing its status, owner or priority. Kept under the tenant that holds the alert (the client's, for an alert
-- CORE forwarded), with the author's name as it was when written. Append-only from the API: a note is never edited. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS alert_notes (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    alert_id    UUID         NOT NULL REFERENCES alerts (id) ON DELETE CASCADE,
    author_id   UUID,
    author      VARCHAR(160) NOT NULL DEFAULT '',
    body        TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_notes_alert ON alert_notes (alert_id, created_at);

ALTER TABLE alert_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON alert_notes;
CREATE POLICY tenant_isolation ON alert_notes
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
