-- Migration 145: the owner's own decisions about which addresses are the same person on the Identities page.
--
-- kind 'merge': these two addresses are one person. kind 'separate': they are NOT, so no automatic rule may join them. The pair is stored sorted (address_a < address_b) per client, so each decision
-- exists once whichever address was clicked first. Decisions are kept by address, not by a person's row, because the tools re-report every address on each refresh.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS identity_merges (
    tenant_id  UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    address_a  VARCHAR(320) NOT NULL,
    address_b  VARCHAR(320) NOT NULL,
    kind       VARCHAR(10)  NOT NULL CHECK (kind IN ('merge', 'separate')),
    created_by UUID,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, address_a, address_b),
    CHECK (address_a < address_b)
);

ALTER TABLE identity_merges ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON identity_merges;
CREATE POLICY tenant_isolation ON identity_merges
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
