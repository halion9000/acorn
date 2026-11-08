-- Migration 163: private links to a read-only status page for one client.
--
-- client_status_links: one row per link the MSSP made for a client. Only a hash of the secret is stored (the secret is shown once, when the link is made). A link works only while it is not revoked, not past its
-- end date and its wording has been reviewed (`reviewed_at`, set by a person after previewing exactly what the client will see). `owner tenant` (tenant_id) is the MSSP; client_id is the client it shows.
-- Looking a link up by its hash happens before any tenant is known, so that one read is explicitly cross-tenant in the code. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_status_links (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    token_hash   VARCHAR(64)  NOT NULL UNIQUE,
    label        VARCHAR(80)  NOT NULL DEFAULT '',
    created_by   UUID,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ  NOT NULL,
    reviewed_at  TIMESTAMPTZ,
    reviewed_by  UUID,
    revoked_at   TIMESTAMPTZ,
    last_opened_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_client_status_links_owner ON client_status_links (tenant_id, client_id);

ALTER TABLE client_status_links ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_status_links;
CREATE POLICY tenant_isolation ON client_status_links
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
