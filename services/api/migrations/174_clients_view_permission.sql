-- ============================================================
-- Migration 174: clients:view, the permission to see the organisation's clients, on for every role that exists
-- ============================================================
-- The client list the pickers read (GET /mssp/children, and the Client Risk Score page's own list) needed mssp:read, which is not in the role editor, so a custom role (the vCIO role) saw only
-- "Own organisation" and nobody could be given it. clients:view is that one thing: the list of clients. It is in the permissions catalog so a role can have it ticked or not.
-- Hal, 2026-11-13: everyone in the organisation sees all clients, and it must stay possible to allow it or not, per role. So every role that exists now is given it here (system and custom, in every
-- organisation), nobody loses sight of a client, and a role made afterwards starts without it. The built-in roles in app/core/security.py hold it in code. Idempotent: a second run adds nothing.
-- ============================================================

INSERT INTO permissions (name, description, category) VALUES
    ('clients:view', 'See the list of the organisation''s clients (the client pickers and client pages). Untick it to keep a role to the organisation''s own data', 'clients')
ON CONFLICT (name) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.name = 'clients:view'
ON CONFLICT (role_id, permission_id) DO NOTHING;
