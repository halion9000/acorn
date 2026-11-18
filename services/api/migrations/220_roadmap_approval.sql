-- Migration 220: who approved a roadmap item that waited on sign-off, and when.
--
-- Pressing Approve on an item that waits on sign-off moves it to "claude" (ready to build) and records the person and the day here. The roadmap sync keeps the approval: it does not move an approved item back to
-- sign-off because the repository file still says so. Idempotent.

BEGIN;

ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS approved_by TEXT;

COMMIT;
