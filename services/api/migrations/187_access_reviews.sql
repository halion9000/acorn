-- Migration 187: access reviews (Secureframe parity plan: personnel and access reviews).
--
-- access_reviews: a periodic check that the people who have access to a system should still have it: a name, the system, a reviewer, a due date, and open or complete.
-- access_review_entries: one line per person with the access they hold, and the reviewer's decision (pending, keep or remove) with a note. The people are a snapshot taken when the review starts
-- (from the Microsoft 365 people A.C.O.R.N holds, or from another tool's people, or typed in), so what was decided stays as it was. Nothing is deleted. Row-level security (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS access_reviews (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name         VARCHAR(200)  NOT NULL,
    system       VARCHAR(120)  NOT NULL,
    reviewer     VARCHAR(200),
    due_date     DATE,
    status       VARCHAR(10)   NOT NULL DEFAULT 'open',
    summary      TEXT          NOT NULL DEFAULT '',
    created_by   VARCHAR(320),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    completed_by VARCHAR(320),
    CONSTRAINT access_reviews_status CHECK (status IN ('open', 'complete'))
);

CREATE INDEX IF NOT EXISTS idx_access_reviews_tenant ON access_reviews (tenant_id, status);

CREATE TABLE IF NOT EXISTS access_review_entries (
    id         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    review_id  UUID          NOT NULL REFERENCES access_reviews (id) ON DELETE CASCADE,
    person     VARCHAR(320)  NOT NULL,
    name       VARCHAR(255),
    access     VARCHAR(400)  NOT NULL DEFAULT '',
    flags      JSONB         NOT NULL DEFAULT '[]'::jsonb,
    decision   VARCHAR(10)   NOT NULL DEFAULT 'pending',
    note       TEXT          NOT NULL DEFAULT '',
    decided_by VARCHAR(320),
    decided_at TIMESTAMPTZ,
    CONSTRAINT access_review_entries_decision CHECK (decision IN ('pending', 'keep', 'remove'))
);

CREATE INDEX IF NOT EXISTS idx_access_review_entries_review ON access_review_entries (review_id, decision);

ALTER TABLE access_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON access_reviews;
CREATE POLICY tenant_isolation ON access_reviews
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE access_review_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON access_review_entries;
CREATE POLICY tenant_isolation ON access_review_entries
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
