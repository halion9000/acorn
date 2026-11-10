-- ============================================================
-- Migration 169: inventory:checkout, a narrow permission for checking a device out to a person and back in
-- ============================================================
-- Checking an item out (to a person or a site) and back in needed inventory:write, which also guards adding, changing, deleting, bulk editing, syncing and importing inventory and is held only by
-- administrators. A technician who hands out a laptop got "API 403" on the check-out button. inventory:checkout is exactly two routes:
--   POST /inventory/{id}/check-out      POST /inventory/{id}/check-in
-- The technician roles (soc_lead, soc_analyst) now hold it. Nobody loses anything and nothing needs backfilling: inventory:write IMPLIES inventory:checkout in app/core/security.py (IMPLIED_BY, used by
-- permission_in, which every check goes through). This migration only adds the name to the permissions catalog so a custom role can be given it on its own. It is idempotent.
-- ============================================================

INSERT INTO permissions (name, description, category) VALUES
    ('inventory:checkout', 'Check an inventory item out to a person or a site and back in (not adding, changing, deleting, syncing or importing items)', 'inventory')
ON CONFLICT (name) DO NOTHING;
