-- Migration 177: HaloPSA tickets made from a Client Risk Score question.
--
-- vcio_risk_tickets: one ticket a person asked for on one question of a risk-scored review ("Create a HaloPSA ticket" on the question's line): the name and private note they gave, the number
-- HaloPSA gave it once CORE opened it, and the ticket's status as CORE last read it from HaloPSA ("On Hold", "Waiting on Customer"...), so the question's line can show where the work is.
-- A.C.O.R.N holds no HaloPSA key: it queues the request for CORE (the vendor_actions queue) and CORE reports back. A question can have several tickets over time.
-- Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS vcio_risk_tickets (
    id                 UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    assessment_id      UUID          NOT NULL REFERENCES vcio_risk_assessments (id) ON DELETE CASCADE,
    question_id        VARCHAR(40)   NOT NULL,
    summary            VARCHAR(200)  NOT NULL,
    private_note       TEXT          NOT NULL DEFAULT '',
    state              VARCHAR(12)   NOT NULL DEFAULT 'waiting',
    ticket_id          VARCHAR(20),
    status             VARCHAR(100),
    status_checked_at  TIMESTAMPTZ,
    message            TEXT,
    created_by         VARCHAR(320),
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT vcio_risk_tickets_state CHECK (state IN ('waiting', 'opened', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_vcio_risk_tickets_assessment ON vcio_risk_tickets (assessment_id, created_at);
CREATE INDEX IF NOT EXISTS idx_vcio_risk_tickets_ticket ON vcio_risk_tickets (tenant_id, ticket_id) WHERE ticket_id IS NOT NULL;

ALTER TABLE vcio_risk_tickets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vcio_risk_tickets;
CREATE POLICY tenant_isolation ON vcio_risk_tickets
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
