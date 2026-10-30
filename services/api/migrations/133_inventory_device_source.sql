-- Migration 133: inventory items can come from the device list (NinjaOne and Addigy).
--
-- source gains 'device': a Windows computer, Mac, iPad or iPhone a tool reports that is not already on the imported lists. Such an item starts as 'checked_out' (it is out at the client), is filed under the device's own client,
-- and carries external_ref 'dev:<device id>' so syncing again refreshes it instead of adding it twice. Idempotent.

BEGIN;

ALTER TABLE inventory_items DROP CONSTRAINT IF EXISTS inventory_items_source_check;
ALTER TABLE inventory_items ADD CONSTRAINT inventory_items_source_check CHECK (source IN ('manual', 'csv', 'device'));

COMMIT;
