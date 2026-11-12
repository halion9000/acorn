-- Migration 172: vCIO Risk Scoring.
--
-- vcio_risk_assessments: one risk-scored Business Review of a client on a review date (Live Oak's scoring workbook, kept in A.C.O.R.N instead of in a spreadsheet per client). It holds
-- the answers (question id -> answer, the vendor in use and a note), any severity the assessor changed for a question, and the scoring settings used. The score, rating and number of
-- questions answered are stored with it so a list of assessments does not have to score each one again. A client can have many (one per review), newest first.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS vcio_risk_assessments (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    review_date  DATE          NOT NULL,
    platform     VARCHAR(10)   NOT NULL DEFAULT 'm365',
    assessor     VARCHAR(200)  NOT NULL DEFAULT '',
    answers      JSONB         NOT NULL DEFAULT '{}'::jsonb,
    severity     JSONB         NOT NULL DEFAULT '{}'::jsonb,
    settings     JSONB         NOT NULL DEFAULT '{}'::jsonb,
    score        REAL,
    rating       VARCHAR(10)   NOT NULL DEFAULT 'na',
    answered     INTEGER       NOT NULL DEFAULT 0,
    created_by   VARCHAR(320),
    updated_by   VARCHAR(320),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT vcio_risk_assessments_platform CHECK (platform IN ('m365', 'google', 'both'))
);

CREATE INDEX IF NOT EXISTS idx_vcio_risk_assessments_client ON vcio_risk_assessments (tenant_id, review_date DESC, created_at DESC);

ALTER TABLE vcio_risk_assessments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vcio_risk_assessments;
CREATE POLICY tenant_isolation ON vcio_risk_assessments
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
