-- Migration 103: history of each client's tool checks, accepted risks, and the last run of each of CORE's sweeps.
--
-- client_check_history: one row each time a check first appears for a client or its status changes (not on every refresh), with the status it had before. The newest row for a check says since when it has
-- had its current status; the rows together are the trend. Written when CORE sends a client's checks (see apply_m365_checks).
--
-- client_check_acceptances: a person accepting a failing check for a client, with a reason and an optional end date. The check still shows what it found; the page marks it accepted until the date.
--
-- core_sweep_runs: the latest pass of each of CORE's per-client sweeps (how many clients, sent, failed, waiting to be mapped, the first error), reported by CORE at the end of every pass, so the page can
-- say which tools are reaching A.C.O.R.N and which are stale. One row per source for the account that owns the feed.
--
-- Row-level security with the standard policy, honouring the fail-closed switch (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS client_check_history (
    id              BIGSERIAL    PRIMARY KEY,
    tenant_id       UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source          VARCHAR(40)  NOT NULL,
    key             VARCHAR(80)  NOT NULL,
    status          VARCHAR(12)  NOT NULL,
    previous_status VARCHAR(12),
    evidence        VARCHAR(300) NOT NULL DEFAULT '',
    observed_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_client_check_history_tenant_key ON client_check_history (tenant_id, key, observed_at DESC);

CREATE TABLE IF NOT EXISTS client_check_acceptances (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key         VARCHAR(80)  NOT NULL,
    reason      VARCHAR(400) NOT NULL,
    accepted_by UUID,
    accepted_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, key)
);

CREATE TABLE IF NOT EXISTS core_sweep_runs (
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    source      VARCHAR(40)  NOT NULL,
    title       VARCHAR(120) NOT NULL,
    ran_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    accounts    INTEGER      NOT NULL DEFAULT 0,
    sent        INTEGER      NOT NULL DEFAULT 0,
    failed      INTEGER      NOT NULL DEFAULT 0,
    waiting     INTEGER      NOT NULL DEFAULT 0,
    skipped     INTEGER      NOT NULL DEFAULT 0,
    first_error VARCHAR(300) NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, source)
);

ALTER TABLE client_check_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_check_history;
CREATE POLICY tenant_isolation ON client_check_history
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE client_check_acceptances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON client_check_acceptances;
CREATE POLICY tenant_isolation ON client_check_acceptances
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

ALTER TABLE core_sweep_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON core_sweep_runs;
CREATE POLICY tenant_isolation ON core_sweep_runs
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
