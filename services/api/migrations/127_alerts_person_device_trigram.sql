-- Migration 127: let the alert list's person and device filters use an index.
--
-- ``GET /alerts?user=`` and ``?device=`` look for a quoted name inside the alert's ``affected_users`` / ``affected_hosts`` JSON text with ``lower(CAST(col AS TEXT)) LIKE '%"name"%'``, which no ordinary index can serve, so
-- every filtered page read every alert of the client (or of every client, for an organization's rolled-up list). A trigram index on exactly that expression turns it into an index lookup.
--
-- It needs the pg_trgm extension. If it cannot be created here (a role without the right), the migration says so and leaves the filters as they were: slower, not broken. Safe to run twice.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm could not be created (%): the person and device filters keep scanning', SQLERRM;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS ix_alerts_affected_users_trgm ON alerts USING gin (lower((affected_users)::text) gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS ix_alerts_affected_hosts_trgm ON alerts USING gin (lower((affected_hosts)::text) gin_trgm_ops);
    END IF;
END $$;
