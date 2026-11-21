-- Migration 241: a security questionnaire sent to a vendor as a form with a link (Hal 2026-11-21, r7-af-06: build as public).
--
-- One row per link: which vendor it is for, when it stops working (30 days unless set), when the vendor answered and what they answered. Only a hash of the token is stored. The public page looks
-- the hash up across organizations (the vendor has no sign-in). Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS vendor_questionnaire_links (
    id               UUID         PRIMARY KEY,
    tenant_id        UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    vendor_id        UUID         NOT NULL REFERENCES vendors (id) ON DELETE CASCADE,
    token_hash       TEXT         NOT NULL,
    expires_at       TIMESTAMPTZ  NOT NULL,
    submitted_at     TIMESTAMPTZ,
    respondent_name  TEXT,
    respondent_email TEXT,
    answers          JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_by       TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS vendor_questionnaire_links_hash_idx ON vendor_questionnaire_links (token_hash);
CREATE INDEX IF NOT EXISTS vendor_questionnaire_links_vendor_idx ON vendor_questionnaire_links (tenant_id, vendor_id);

ALTER TABLE vendor_questionnaire_links ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendor_questionnaire_links;
CREATE POLICY tenant_isolation ON vendor_questionnaire_links
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
