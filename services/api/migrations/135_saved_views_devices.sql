-- Migration 135: let a person save named filter views on the Devices page.
--
-- Migration 037 limited `view_type` to alerts, cases, investigations and playbooks. The Devices page now has the same "Saved views" bar, so a saved view of type 'devices' must pass the check; against
-- a database built from 037 alone that insert would fail. Nothing else about the table changes.
--
-- Idempotent: the old constraint is dropped if present and the wider one is added in its place.

BEGIN;

ALTER TABLE saved_views DROP CONSTRAINT IF EXISTS saved_views_view_type_check;
ALTER TABLE saved_views ADD CONSTRAINT saved_views_view_type_check CHECK (view_type IN ('alerts', 'cases', 'investigations', 'playbooks', 'devices'));

COMMIT;
