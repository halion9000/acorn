-- Migration 111: why a difference between what is billed and what is counted is accepted.
--
-- billing_difference_notes: one row per client and invoice line: a note ("flat package", "minimum of 10 seats") and the difference (counted minus billed) it was written for. The billed-versus-counted view
-- shows the line as accepted while the difference is still that number; when the difference changes, the note is shown as out of date and the line needs a look again. Owned by the account that owns the
-- feed (tenant_id), one row per client (client_id). Quantities only. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS billing_difference_notes (
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    invoice_item VARCHAR(120) NOT NULL,
    note         VARCHAR(400) NOT NULL,
    difference   INTEGER      NOT NULL,
    updated_by   UUID,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, client_id, invoice_item)
);

ALTER TABLE billing_difference_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON billing_difference_notes;
CREATE POLICY tenant_isolation ON billing_difference_notes
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
