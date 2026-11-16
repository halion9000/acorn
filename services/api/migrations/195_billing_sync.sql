-- Migration 195: Billing sync, the approve-and-push page (Sales and Finance), and the built-in billing role.
--
-- billing:push is the permission to approve a license-count difference and have CORE write the counted quantity to the client's recurring invoice line in HaloPSA. Nobody holds it by default except
-- the new built-in `billing` role and the wildcard holders; it is in the permissions catalog so a custom role or an API key can be given it.
-- vendor_actions gets a new action, 'halo_billing_update' (A.C.O.R.N holds no HaloPSA key: the push is queued for CORE, vendor 'core', like every other write).
-- billing_sync_items: per client and invoice line, whether a person hid it from the list, and the last push (the vendor action's id, who asked, what quantity), so the page can show its outcome.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

INSERT INTO permissions (name, description, category) VALUES
    ('billing:push', 'Approve a license-count difference and push the counted quantity to the recurring invoice in HaloPSA', 'billing')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search', 'create_ticket', 'release_quarantine', 'ticket_note', 'quarantine_check', 'allow_sender', 'create_halo_user', 'addigy_push', 'sc_command', 'ninja_deploy', 'halo_billing_update'));

CREATE TABLE IF NOT EXISTS billing_sync_items (
    tenant_id      UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_id      UUID         NOT NULL,
    invoice_item   TEXT         NOT NULL,
    hidden         BOOLEAN      NOT NULL DEFAULT FALSE,
    action_id      UUID,
    pushed_quantity INTEGER,
    pushed_by      TEXT,
    pushed_at      TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, client_id, invoice_item)
);

ALTER TABLE billing_sync_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON billing_sync_items;
CREATE POLICY tenant_isolation ON billing_sync_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
