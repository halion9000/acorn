-- Migration 235: versions of the datasets CORE sends (SIEM style storage, step 3 of 5; roadmap siem-3-snapshot-versions).
--
-- Each Metrics dataset (weekly staff facts, ticket detail, invoice lines, licenses, roles...) is a latest snapshot that is replaced when CORE sends again. Every version that differs from the one before, at most one
-- every six hours per dataset, is now also kept here, append-only like the event store (update refused; delete refused except by the retention purge or when the organization is deleted). SHA-256 of the content is kept so
-- a version can be checked and an identical one is never stored twice. Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS dataset_versions (
    id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    key          TEXT         NOT NULL,
    received_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sha256       TEXT         NOT NULL,
    payload      JSONB        NOT NULL,
    CONSTRAINT dataset_versions_once UNIQUE (tenant_id, key, sha256)
);
CREATE INDEX IF NOT EXISTS dataset_versions_key_time_idx ON dataset_versions (tenant_id, key, received_at DESC);

CREATE OR REPLACE FUNCTION dataset_versions_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('aisoc.event_purge', true) = 'on' OR NOT EXISTS (SELECT 1 FROM tenants WHERE id = OLD.tenant_id) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'dataset_versions rows are never changed (attempted %)', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS dataset_versions_append_only ON dataset_versions;
CREATE TRIGGER dataset_versions_append_only
    BEFORE UPDATE OR DELETE ON dataset_versions
    FOR EACH ROW EXECUTE FUNCTION dataset_versions_append_only();

ALTER TABLE dataset_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON dataset_versions;
CREATE POLICY tenant_isolation ON dataset_versions
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
