-- Migration 198: a note on each automatic-ticket rule (Settings, Tickets).
--
-- The note is written into every ticket the rule opens, under "Instructions", so the person who gets the ticket is told what to do about this type of alert. Empty means no note. Idempotent.

BEGIN;

ALTER TABLE alert_ticket_rules ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT '';

COMMIT;
