-- Migration 167: how many hits a saved hunt returned the last time the scheduler ran it.
--
-- aisoc_saved_hunts.last_hit_count: the number of rows the hunt's query returned on its latest scheduled run (NULL until it has run). Shown on the /hunt page beside "Last run" so an analyst can see a standing
-- hunt is finding something (or nothing) without opening it. No new table, so the existing row-level security applies unchanged. Idempotent.

BEGIN;

ALTER TABLE aisoc_saved_hunts ADD COLUMN IF NOT EXISTS last_hit_count INTEGER;

COMMIT;
