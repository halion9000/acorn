-- Migration 234: the event store (SIEM style storage, step 2 of 5; roadmap siem-2-event-store).
--
-- One append-only table that every source can write into: the client the event is about, the source and kind, when the event happened, when CORE pulled it, an external id (so the same event is never kept twice) and the
-- whole event as JSON. Rows are never changed: an update is refused, and a delete is refused except by the retention purge (it sets aisoc.event_purge for its own transaction) or when the organization itself is deleted.
-- Row-level security as in migration 081. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS stored_events (
    id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    UUID         NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    client_id    UUID,
    source       TEXT         NOT NULL,
    kind         TEXT         NOT NULL,
    event_time   TIMESTAMPTZ  NOT NULL,
    pulled_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    external_id  TEXT         NOT NULL,
    payload      JSONB        NOT NULL,
    CONSTRAINT stored_events_once UNIQUE (tenant_id, source, kind, external_id)
);
CREATE INDEX IF NOT EXISTS stored_events_client_time_idx ON stored_events (tenant_id, client_id, event_time DESC);
CREATE INDEX IF NOT EXISTS stored_events_source_time_idx ON stored_events (tenant_id, source, kind, event_time DESC);

CREATE OR REPLACE FUNCTION stored_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('aisoc.event_purge', true) = 'on' OR NOT EXISTS (SELECT 1 FROM tenants WHERE id = OLD.tenant_id) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'stored_events rows are never changed (attempted %)', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS stored_events_append_only ON stored_events;
CREATE TRIGGER stored_events_append_only
    BEFORE UPDATE OR DELETE ON stored_events
    FOR EACH ROW EXECUTE FUNCTION stored_events_append_only();

ALTER TABLE stored_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON stored_events;
CREATE POLICY tenant_isolation ON stored_events
    USING ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))))
    WITH CHECK ((tenant_id = current_tenant_id()) OR ((current_tenant_id() IS NULL) AND (NOT (SELECT rls_fail_closed()))));

COMMIT;
