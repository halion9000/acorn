-- Migration 221: a text box on each roadmap item for the person's answers and questions.
--
-- The status line (note) is the assistant's: it says what an item waits for or asks a question. ``reply`` is the person's: an answer or a question written on the page. The sync never touches it; the assistant reads it
-- from the live list and answers by updating the status line. Idempotent.

BEGIN;

ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS reply TEXT NOT NULL DEFAULT '';
ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS reply_at TIMESTAMPTZ;
ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS reply_by TEXT;

COMMIT;
