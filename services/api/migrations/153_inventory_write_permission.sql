-- ============================================================
-- Migration 153: inventory:write, so a custom role can be allowed to manage inventory (and nothing else of the MSSP console)
-- ============================================================
-- Adding, changing, checking in and out, syncing and importing inventory items all needed mssp:manage. That permission was never in the permissions catalog, so a
-- custom role could not be given it from the role editor, and giving it would have meant the whole MSSP console anyway. inventory:write is the narrow one.
--
-- Nobody loses anything and nothing needs backfilling: mssp:manage IMPLIES inventory:write in app/core/security.py (IMPLIED_BY, used by permission_in, which every
-- check goes through). This migration only adds the name to the catalog. It is idempotent.
-- ============================================================

INSERT INTO permissions (name, description, category) VALUES
    ('inventory:write', 'Add, change, check in and out, sync and import inventory items', 'inventory')
ON CONFLICT (name) DO NOTHING;
