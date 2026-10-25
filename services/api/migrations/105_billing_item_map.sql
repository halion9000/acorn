-- Migration 105: which tool counts an invoice line is checked against.
--
-- billing_item_map: one row per invoice line description HaloPSA bills (for example "Huntress for Workstations (Included)"), naming the tool counts it should equal. ``counted`` is a list of
-- {source, item} (a tool's own name and the item it counts): their counts are added and compared with the quantity billed. Owned by the account that owns the feed (tenant_id), not by a client: the
-- same invoice line means the same thing for every client. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS billing_item_map (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    invoice_item VARCHAR(120) NOT NULL,
    counted      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    updated_by   UUID,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, invoice_item)
);

ALTER TABLE billing_item_map ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON billing_item_map;
CREATE POLICY tenant_isolation ON billing_item_map
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
