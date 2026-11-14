-- Migration 180: the risk register (Secureframe parity plan, step 1).
--
-- risk_register_items: one risk of one organization (or one of its clients): what it is, its category and owner, likelihood and impact (1 to 5 each) before treatment, what was decided
-- (mitigate, accept, transfer, avoid, undecided) and the likelihood and impact left after it. The score is likelihood times impact and is worked out in code, never stored.
-- risk_register_tasks: the work that treats a risk, with an owner and a due date.
-- risk_register_history: who changed what and when, one line per change, kept even after the risk is archived.
-- A risk is never deleted from the page: it is archived (status 'archived') and can be restored. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS risk_register_items (
    id                   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    ref_no               INTEGER       NOT NULL,
    title                VARCHAR(300)  NOT NULL,
    description          TEXT          NOT NULL DEFAULT '',
    category             VARCHAR(60)   NOT NULL DEFAULT 'Other',
    owner                VARCHAR(200),
    likelihood           SMALLINT      NOT NULL,
    impact               SMALLINT      NOT NULL,
    treatment            VARCHAR(10)   NOT NULL DEFAULT 'undecided',
    treatment_note       TEXT          NOT NULL DEFAULT '',
    residual_likelihood  SMALLINT,
    residual_impact      SMALLINT,
    status               VARCHAR(12)   NOT NULL DEFAULT 'open',
    archived_at          TIMESTAMPTZ,
    created_by           VARCHAR(320),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT risk_register_items_ref UNIQUE (tenant_id, ref_no),
    CONSTRAINT risk_register_items_scale CHECK (likelihood BETWEEN 1 AND 5 AND impact BETWEEN 1 AND 5),
    CONSTRAINT risk_register_items_residual CHECK ((residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND 5) AND (residual_impact IS NULL OR residual_impact BETWEEN 1 AND 5)),
    CONSTRAINT risk_register_items_treatment CHECK (treatment IN ('mitigate', 'accept', 'transfer', 'avoid', 'undecided')),
    CONSTRAINT risk_register_items_status CHECK (status IN ('open', 'assessed', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_risk_register_items_tenant ON risk_register_items (tenant_id, status);

CREATE TABLE IF NOT EXISTS risk_register_tasks (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    risk_id     UUID          NOT NULL REFERENCES risk_register_items (id) ON DELETE CASCADE,
    title       VARCHAR(300)  NOT NULL,
    owner       VARCHAR(200),
    due_date    DATE,
    done        BOOLEAN       NOT NULL DEFAULT false,
    done_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_register_tasks_risk ON risk_register_tasks (risk_id, created_at);

CREATE TABLE IF NOT EXISTS risk_register_history (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID          NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    risk_id     UUID          NOT NULL REFERENCES risk_register_items (id) ON DELETE CASCADE,
    actor       VARCHAR(320),
    action      VARCHAR(40)   NOT NULL,
    detail      TEXT          NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_register_history_risk ON risk_register_history (risk_id, created_at);

ALTER TABLE risk_register_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_register_items;
CREATE POLICY tenant_isolation ON risk_register_items
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE risk_register_tasks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_register_tasks;
CREATE POLICY tenant_isolation ON risk_register_tasks
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE risk_register_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_register_history;
CREATE POLICY tenant_isolation ON risk_register_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
