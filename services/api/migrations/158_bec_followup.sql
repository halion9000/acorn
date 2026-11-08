-- Migration 158: a BEC search started by a person also opens a case and a HaloPSA ticket, and writes the result on both.
--
-- bec_cases remembers which case (aisoc_cases) and which ticket belong to the search, and whether the result has been written on the ticket. Idempotent.

BEGIN;

ALTER TABLE bec_cases ADD COLUMN IF NOT EXISTS aisoc_case_id uuid;
ALTER TABLE bec_cases ADD COLUMN IF NOT EXISTS ticket_id varchar(12);
ALTER TABLE bec_cases ADD COLUMN IF NOT EXISTS ticket_note_queued boolean NOT NULL DEFAULT false;

COMMIT;
