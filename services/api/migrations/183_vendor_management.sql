-- Migration 183: vendor management (Secureframe parity plan, step 2): the third parties an organization (or one of its clients) depends on.
--
-- vendors: one row per vendor: what it is and does for the organization, who owns the relationship, the risk level a person set, how it signs in, the contract dates and how often it is reviewed. Never deleted from
-- the page: archived (status 'archived') and restorable.
-- vendor_reviews: a security review of a vendor (a recurring one comes due every review_interval_months after the last completed one, or a one-time one), with its status and what it found.
-- vendor_documents: the documents held for a vendor (a SOC report, a contract, a questionnaire): a name, a kind and a link. The file itself is not stored here.
-- vendor_history: one line per change. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS vendors (
    id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name                    VARCHAR(200)  NOT NULL,
    website                 VARCHAR(300),
    trust_url               VARCHAR(500),
    service                 VARCHAR(300),
    category                VARCHAR(60)   NOT NULL DEFAULT 'Other',
    owner                   VARCHAR(200),
    risk_level              VARCHAR(10)   NOT NULL DEFAULT 'unassessed',
    data_access             VARCHAR(12)   NOT NULL DEFAULT 'unknown',
    auth_type               VARCHAR(60),
    mfa                     BOOLEAN,
    account_manager_name    VARCHAR(200),
    account_manager_email   VARCHAR(320),
    contract_start          DATE,
    contract_end            DATE,
    review_interval_months  SMALLINT,
    notes                   TEXT          NOT NULL DEFAULT '',
    status                  VARCHAR(10)   NOT NULL DEFAULT 'active',
    archived_at             TIMESTAMPTZ,
    created_by              VARCHAR(320),
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT vendors_risk CHECK (risk_level IN ('unassessed', 'low', 'medium', 'high', 'critical')),
    CONSTRAINT vendors_data CHECK (data_access IN ('unknown', 'none', 'internal', 'sensitive')),
    CONSTRAINT vendors_status CHECK (status IN ('active', 'archived')),
    CONSTRAINT vendors_interval CHECK (review_interval_months IS NULL OR review_interval_months BETWEEN 1 AND 60)
);

CREATE INDEX IF NOT EXISTS idx_vendors_tenant ON vendors (tenant_id, status);

CREATE TABLE IF NOT EXISTS vendor_reviews (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor_id     UUID          NOT NULL REFERENCES vendors (id) ON DELETE CASCADE,
    kind          VARCHAR(10)   NOT NULL DEFAULT 'one_time',
    title         VARCHAR(300)  NOT NULL,
    start_date    DATE          NOT NULL,
    due_date      DATE          NOT NULL,
    status        VARCHAR(12)   NOT NULL DEFAULT 'in_progress',
    reviewer      VARCHAR(200),
    outcome       VARCHAR(12),
    findings      TEXT          NOT NULL DEFAULT '',
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT vendor_reviews_kind CHECK (kind IN ('recurring', 'one_time')),
    CONSTRAINT vendor_reviews_status CHECK (status IN ('in_progress', 'complete')),
    CONSTRAINT vendor_reviews_outcome CHECK (outcome IS NULL OR outcome IN ('no_concerns', 'concerns'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_reviews_vendor ON vendor_reviews (vendor_id, created_at);

CREATE TABLE IF NOT EXISTS vendor_documents (
    id         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor_id  UUID          NOT NULL REFERENCES vendors (id) ON DELETE CASCADE,
    name       VARCHAR(300)  NOT NULL,
    doc_type   VARCHAR(40)   NOT NULL DEFAULT 'Other',
    url        VARCHAR(1000),
    added_by   VARCHAR(320),
    added_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_documents_vendor ON vendor_documents (vendor_id, added_at);

CREATE TABLE IF NOT EXISTS vendor_history (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor_id   UUID          NOT NULL REFERENCES vendors (id) ON DELETE CASCADE,
    actor       VARCHAR(320),
    action      VARCHAR(40)   NOT NULL,
    detail      TEXT          NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_history_vendor ON vendor_history (vendor_id, created_at);

ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendors;
CREATE POLICY tenant_isolation ON vendors
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE vendor_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendor_reviews;
CREATE POLICY tenant_isolation ON vendor_reviews
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE vendor_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendor_documents;
CREATE POLICY tenant_isolation ON vendor_documents
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE vendor_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendor_history;
CREATE POLICY tenant_isolation ON vendor_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
