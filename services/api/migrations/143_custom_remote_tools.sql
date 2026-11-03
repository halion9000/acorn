-- Migration 143: remote tools the owner adds to the catalog by hand.
--
-- custom_remote_tools: one row per tool the managing company added from the Remote tools page, for a program the built-in list does not know. match_text is a piece of the program's name as the
-- device lists it (matched as whole words, any case); publisher_text, when given, must also appear in the publisher. tool_key is generated ("custom_<name>") and is what rules and sightings refer to.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS custom_remote_tools (
    tenant_id      UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    tool_key       VARCHAR(60)   NOT NULL,
    name           VARCHAR(120)  NOT NULL,
    category       VARCHAR(30)   NOT NULL,
    match_text     VARCHAR(80)   NOT NULL,
    publisher_text VARCHAR(80),
    created_by     UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tool_key)
);

ALTER TABLE custom_remote_tools ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON custom_remote_tools;
CREATE POLICY tenant_isolation ON custom_remote_tools
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
