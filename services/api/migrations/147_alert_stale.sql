-- Migration 147: stale alerts, set aside for review instead of left open for ever.
--
-- An alert nobody has touched for ALERT_STALE_DAYS (30 by default), that is not critical or high and belongs to no case, is moved to the status 'stale': out of the open counts and the default lists, still
-- there, and visible under the Stale filter where it can be restored or closed in bulk. Nothing is deleted. The status it had is kept so a restore puts it back exactly as it was.
-- Idempotent.

BEGIN;

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS status_before_stale VARCHAR(30);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS stale_at TIMESTAMPTZ;

COMMIT;
