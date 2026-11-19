-- Migration 227: client families (roadmap huntress-family): a parent company and its linked child clients, so group records can follow to a sibling.
-- A family is a name owned by the MSSP tenant; each member is one of its clients, in at most one family. Nothing about a client's own data changes: this is a read-only link.
-- Row-level security as in migration 081 (owner tenant). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_families (
    id          UUID          PRIMARY KEY,
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name        VARCHAR(120)  NOT NULL,
    created_by  VARCHAR(320),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS client_families_name_idx ON client_families (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS client_family_members (
    tenant_id        UUID  NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    family_id        UUID  NOT NULL REFERENCES client_families (id) ON DELETE CASCADE,
    client_tenant_id UUID  NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    PRIMARY KEY (tenant_id, client_tenant_id)
);
CREATE INDEX IF NOT EXISTS client_family_members_family_idx ON client_family_members (family_id);

ALTER TABLE client_families ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_families;
CREATE POLICY tenant_isolation ON client_families
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE client_family_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_family_members;
CREATE POLICY tenant_isolation ON client_family_members
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
