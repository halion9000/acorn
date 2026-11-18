-- Migration 211: onboarding and offboarding tasks per person (Compliance, People).
--
-- One row per task for one person (by e-mail address): the kind of checklist it belongs to (onboarding or offboarding), its title, when it is due, and when and by whom it was ticked off. The checklists are started from a
-- built-in list (or a task is added by hand); a person's tasks stay on file after they are done, as the record of what was done. Row-level security with the standard policy (migration 081). Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS personnel_tasks (
    id          UUID         PRIMARY KEY,
    tenant_id   UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    email       TEXT         NOT NULL,
    kind        TEXT         NOT NULL,
    title       TEXT         NOT NULL,
    due_on      DATE,
    created_by  TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    done_at     TIMESTAMPTZ,
    done_by     TEXT,
    CONSTRAINT personnel_tasks_kind CHECK (kind IN ('onboarding', 'offboarding')),
    CONSTRAINT personnel_tasks_title UNIQUE (tenant_id, email, kind, title)
);

CREATE INDEX IF NOT EXISTS personnel_tasks_person_idx ON personnel_tasks (tenant_id, email);

ALTER TABLE personnel_tasks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON personnel_tasks;
CREATE POLICY tenant_isolation ON personnel_tasks
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
