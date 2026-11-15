-- Migration 185: roadmap items can be removed and a person's own status change is kept.
--
-- removed_at: set when a person removes an item. The item stays in the table (nothing is deleted) but is no longer listed, and the repository sync never brings a removed item back.
-- person_status: set when a person moves an item's status on the page. The repository sync then leaves that item's status alone, unless the file says completed. Idempotent.

BEGIN;

ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;
ALTER TABLE roadmap_items ADD COLUMN IF NOT EXISTS person_status BOOLEAN NOT NULL DEFAULT false;

COMMIT;
