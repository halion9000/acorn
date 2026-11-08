-- Migration 165: a review calendar and a policy library.
--
-- governance_items: one row per thing that must be looked at again on a schedule (a policy, a vendor, a piece of evidence, anything else): who owns it, how often (interval_days), when it is next due and when it
-- was last reviewed. A policy item can also keep its text in versions.
-- governance_versions: each saved version of a policy's text (append-only: an old version is never edited, only a newer one is added), with who saved it and a short note of what changed.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS governance_items (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    kind             VARCHAR(20)  NOT NULL CHECK (kind IN ('policy', 'vendor', 'evidence', 'other')),
    title            VARCHAR(160) NOT NULL,
    owner            VARCHAR(120) NOT NULL DEFAULT '',
    notes            TEXT         NOT NULL DEFAULT '',
    interval_days    INTEGER      NOT NULL CHECK (interval_days BETWEEN 1 AND 1095),
    next_due         DATE         NOT NULL,
    last_reviewed_at DATE,
    created_by       UUID,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    archived_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_governance_items_tenant_due ON governance_items (tenant_id, next_due) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS governance_versions (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id     UUID         NOT NULL REFERENCES governance_items (id) ON DELETE CASCADE,
    version     INTEGER      NOT NULL,
    body        TEXT         NOT NULL,
    change_note VARCHAR(300) NOT NULL DEFAULT '',
    created_by  UUID,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (item_id, version)
);

ALTER TABLE governance_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON governance_items;
CREATE POLICY tenant_isolation ON governance_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE governance_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON governance_versions;
CREATE POLICY tenant_isolation ON governance_versions
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
