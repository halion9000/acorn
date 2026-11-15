-- Migration 188: security questionnaires (Secureframe parity plan).
--
-- questionnaire_answers: the answer library: a question as customers ask it, the answer to give, a category, and when a person last confirmed it is still true. Archived, never deleted.
-- questionnaires: one customer questionnaire being answered: a name, the customer, a due date, open or complete.
-- questionnaire_items: its questions in order, each with the answer drafted from the library (or typed), where it came from, and whether a person approved it. Row-level security (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS questionnaire_answers (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    question      TEXT          NOT NULL,
    answer        TEXT          NOT NULL,
    category      VARCHAR(80)   NOT NULL DEFAULT 'General',
    last_reviewed DATE,
    created_by    VARCHAR(320),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    archived_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_questionnaire_answers_tenant ON questionnaire_answers (tenant_id);

CREATE TABLE IF NOT EXISTS questionnaires (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name        VARCHAR(200)  NOT NULL,
    customer    VARCHAR(200),
    due_date    DATE,
    status      VARCHAR(10)   NOT NULL DEFAULT 'open',
    created_by  VARCHAR(320),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT questionnaires_status CHECK (status IN ('open', 'complete'))
);
CREATE INDEX IF NOT EXISTS idx_questionnaires_tenant ON questionnaires (tenant_id, status);

CREATE TABLE IF NOT EXISTS questionnaire_items (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    questionnaire_id UUID          NOT NULL REFERENCES questionnaires (id) ON DELETE CASCADE,
    position         INTEGER       NOT NULL,
    question         TEXT          NOT NULL,
    answer           TEXT          NOT NULL DEFAULT '',
    source           VARCHAR(10)   NOT NULL DEFAULT 'none',
    library_id       UUID          REFERENCES questionnaire_answers (id) ON DELETE SET NULL,
    match_score      INTEGER       NOT NULL DEFAULT 0,
    approved         BOOLEAN       NOT NULL DEFAULT false,
    approved_by      VARCHAR(320),
    CONSTRAINT questionnaire_items_source CHECK (source IN ('none', 'library', 'manual'))
);
CREATE INDEX IF NOT EXISTS idx_questionnaire_items_q ON questionnaire_items (questionnaire_id, position);

ALTER TABLE questionnaire_answers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON questionnaire_answers;
CREATE POLICY tenant_isolation ON questionnaire_answers
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE questionnaires ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON questionnaires;
CREATE POLICY tenant_isolation ON questionnaires
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE questionnaire_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON questionnaire_items;
CREATE POLICY tenant_isolation ON questionnaire_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
