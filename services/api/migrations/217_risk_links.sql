-- Migration 217: links from a risk to the controls and vendors it concerns (Risk register).
--
-- One row per link: kind is control (framework and control id from the compliance catalog) or vendor (ref is the vendor id). A risk cannot link the same thing twice.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS risk_register_links (
    id          UUID         PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    risk_id     UUID         NOT NULL REFERENCES risk_register_items (id) ON DELETE CASCADE,
    kind        VARCHAR(10)  NOT NULL CHECK (kind IN ('control', 'vendor')),
    framework   VARCHAR(20),
    ref         VARCHAR(80)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS risk_register_links_unique ON risk_register_links (risk_id, kind, COALESCE(framework, ''), ref);
CREATE INDEX IF NOT EXISTS risk_register_links_ref_idx ON risk_register_links (tenant_id, kind, ref);

ALTER TABLE risk_register_links ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_register_links;
CREATE POLICY tenant_isolation ON risk_register_links
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
