-- Migration 129: the history of each client-review question, automatic and typed.
--
-- client_review_history: one row each time a question's worked-out answer changes (source = 'automatic', recorded when the review is read and the status or evidence is not what the last automatic row says) and
-- each time a person types, changes or clears an answer or a note (source = 'manual'). Newest first by `at`. `detail` is the evidence A.C.O.R.N worked out, or the typed answer; `actor` is who typed it.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_review_history (
    id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    section   VARCHAR(12)  NOT NULL CHECK (section IN ('readiness', 'tech', 'm365', 'assess')),
    key       VARCHAR(400) NOT NULL,
    at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    source    VARCHAR(10)  NOT NULL CHECK (source IN ('automatic', 'manual')),
    status    VARCHAR(20),
    detail    VARCHAR(1000),
    note      TEXT,
    actor     VARCHAR(320)
);

CREATE INDEX IF NOT EXISTS ix_client_review_history_question ON client_review_history (tenant_id, section, key, at DESC);

ALTER TABLE client_review_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_review_history;
CREATE POLICY tenant_isolation ON client_review_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
