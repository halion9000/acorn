-- Migration 113: billing:view, the read-only permission for the licence and count pages.
--
-- It guards the GET routes under /billing (what each tool counts for each client, the changes, billed versus counted, the invoice-line map, the data-quality and last-reported views). Nobody loses
-- anything and nothing needs backfilling: alerts:read IMPLIES billing:view in app/core/security.py (permission_in), which every check goes through (static roles, database roles, API-key scopes and
-- a `billing:*` wildcard). This only adds the name to the permissions catalog so a custom role can be given the billing pages on its own. Idempotent.

INSERT INTO permissions (name, description, category) VALUES
    ('billing:view', 'Read what each tool counts for each client, the changes, billed versus counted and the data-quality views (quantities only, no prices)', 'billing')
ON CONFLICT (name) DO NOTHING;
