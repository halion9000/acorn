-- person_tickets: each person's recent tickets in the ticketing tool (HaloPSA), sent by CORE, for the identity page ("the last few tickets"). One row per ticket per client; about 90 days are kept. Safe to run again.
BEGIN;

CREATE TABLE IF NOT EXISTS person_tickets (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source      VARCHAR(40)  NOT NULL,
    ticket_id   VARCHAR(40)  NOT NULL,
    summary     VARCHAR(300) NOT NULL,
    status      VARCHAR(80),
    opened_at   TIMESTAMPTZ  NOT NULL,
    updated_at  TIMESTAMPTZ,
    user_email  VARCHAR(320) NOT NULL,
    user_name   VARCHAR(255),
    url         VARCHAR(500),
    received_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, source, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_person_tickets_person ON person_tickets (tenant_id, user_email, opened_at DESC);

ALTER TABLE person_tickets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON person_tickets;
CREATE POLICY tenant_isolation ON person_tickets
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
