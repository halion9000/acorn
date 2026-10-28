-- client_documents: what a client's documentation system (IT Glue) says about them -- documents, configurations, flexible assets such as runbooks and onboarding guides -- sent by CORE, so Leafy and the people using
-- the console can search it. Text only. Password entries are never sent. One row per record per client; a record not refreshed for two weeks is dropped by the next report. search is a generated full-text column.
BEGIN;

CREATE TABLE IF NOT EXISTS client_documents (
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor      VARCHAR(40)   NOT NULL,
    external_id VARCHAR(80)   NOT NULL,
    kind        VARCHAR(40)   NOT NULL,
    title       VARCHAR(300)  NOT NULL,
    folder      VARCHAR(300),
    body        TEXT          NOT NULL DEFAULT '',
    url         VARCHAR(500),
    vendor_updated_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    search      TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(folder, '') || ' ' || coalesce(body, ''))
    ) STORED,
    PRIMARY KEY (tenant_id, vendor, external_id)
);

CREATE INDEX IF NOT EXISTS idx_client_documents_search ON client_documents USING GIN (search);
CREATE INDEX IF NOT EXISTS idx_client_documents_received ON client_documents (tenant_id, vendor, received_at);

ALTER TABLE client_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_documents;
CREATE POLICY tenant_isolation ON client_documents
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
