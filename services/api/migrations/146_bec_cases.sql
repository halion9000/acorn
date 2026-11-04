-- Migration 146: business email compromise (BEC) searches started from the Identities page.
--
-- A search is a case: A.C.O.R.N queues "bec_search" for CORE (the vendor_actions queue, vendor 'core'), CORE starts CIPP's BEC investigation for the person, follows it and reports progress and then the
-- finished report. bec_cases keeps one row per search: who asked, which person, how far it got and, when it finishes, the report CIPP returned (kept whole in ``report`` so nothing CIPP found is lost, with
-- ``summary`` for what the page shows at a glance). The permission identities:bec allows starting one.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

ALTER TABLE vendor_actions DROP CONSTRAINT IF EXISTS vendor_actions_action_check;
ALTER TABLE vendor_actions ADD CONSTRAINT vendor_actions_action_check
    CHECK (action IN ('approve', 'reject', 'resolve', 'run_script', 'revoke_sessions', 'disable_user', 'enable_user', 'bec_search'));

CREATE TABLE IF NOT EXISTS bec_cases (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    case_ref      VARCHAR(60)  NOT NULL,
    email         VARCHAR(320) NOT NULL,
    status        VARCHAR(10)  NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    step          INTEGER      NOT NULL DEFAULT 0,
    steps_total   INTEGER      NOT NULL DEFAULT 0,
    step_label    VARCHAR(300),
    message       TEXT,
    report        JSONB,
    summary       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    requested_by  UUID,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_bec_cases_person ON bec_cases (tenant_id, email, created_at DESC);

ALTER TABLE bec_cases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON bec_cases;
CREATE POLICY tenant_isolation ON bec_cases
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

INSERT INTO permissions (name, description, category) VALUES
    ('identities:bec', 'Start a business email compromise search for a person from the Identities page (carried out by CORE through CIPP, read only) and read its report', 'identities')
ON CONFLICT (name) DO NOTHING;

COMMIT;
