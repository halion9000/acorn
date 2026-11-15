-- Migration 184: the roadmap (Settings > Upcoming improvements): what is waiting to be built or fixed, who it waits on, how urgent it is and where it stands.
--
-- roadmap_items: one row per item. key is set on items kept in step from the repository file (docs/ROADMAP_ITEMS.json) by app.scripts.roadmap_sync, which owns their title, detail, area, status, needs and note;
-- priority is always the person's to set. An item added on the page has no key and is never touched by the sync. needs: claude (can be done without anyone), signoff (needs a person to approve), hal (needs a person
-- to do something first). Nothing is deleted: a finished item is status completed. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS roadmap_items (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key           VARCHAR(80),
    title         VARCHAR(200)  NOT NULL,
    detail        TEXT          NOT NULL DEFAULT '',
    area          VARCHAR(60)   NOT NULL DEFAULT 'General',
    status        VARCHAR(12)   NOT NULL DEFAULT 'new',
    needs         VARCHAR(8)    NOT NULL DEFAULT 'claude',
    priority      VARCHAR(6)    NOT NULL DEFAULT 'normal',
    note          TEXT          NOT NULL DEFAULT '',
    completed_ref VARCHAR(80),
    created_by    VARCHAR(320),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    CONSTRAINT roadmap_status CHECK (status IN ('new', 'not_started', 'in_progress', 'completed')),
    CONSTRAINT roadmap_needs CHECK (needs IN ('claude', 'signoff', 'hal')),
    CONSTRAINT roadmap_priority CHECK (priority IN ('high', 'normal', 'low'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_roadmap_items_key ON roadmap_items (tenant_id, key) WHERE key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_roadmap_items_tenant ON roadmap_items (tenant_id, status);

ALTER TABLE roadmap_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON roadmap_items;
CREATE POLICY tenant_isolation ON roadmap_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
