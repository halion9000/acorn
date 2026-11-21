-- Migration 240: one-time links for accepting a policy without signing in (Hal 2026-11-21, r7-af-13: outside people such as contractors).
--
-- One row per link: who it is for, which version of which policy it shows, when it stops working and when it was used. Only a hash of the token is stored, so a copy of the database cannot be used to accept
-- anything. The public page looks the hash up across organizations (the visitor has no sign-in). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS policy_accept_links (
    id           UUID         PRIMARY KEY,
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    item_id      UUID         NOT NULL REFERENCES governance_items (id) ON DELETE CASCADE,
    version      INTEGER      NOT NULL,
    email        TEXT         NOT NULL,
    display_name TEXT,
    token_hash   TEXT         NOT NULL,
    expires_at   TIMESTAMPTZ  NOT NULL,
    used_at      TIMESTAMPTZ,
    created_by   TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS policy_accept_links_hash_idx ON policy_accept_links (token_hash);
CREATE INDEX IF NOT EXISTS policy_accept_links_item_idx ON policy_accept_links (tenant_id, item_id);

ALTER TABLE policy_accept_links ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON policy_accept_links;
CREATE POLICY tenant_isolation ON policy_accept_links
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
