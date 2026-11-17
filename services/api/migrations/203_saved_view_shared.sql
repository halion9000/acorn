-- Migration 203: a saved view can be shared with the whole tenant (Devices, Alerts and the other list pages).
--
-- The owner shares or unshares it; others can apply it but not change or delete it. Idempotent.

BEGIN;

ALTER TABLE saved_views ADD COLUMN IF NOT EXISTS shared BOOLEAN NOT NULL DEFAULT false;

COMMIT;
