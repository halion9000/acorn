-- ============================================================
-- Migration 173: vcio:assess, a narrow permission for the Client Risk Score assessments
-- ============================================================
-- Starting, answering, filling in and deleting a Client Risk Score assessment needed mssp:manage, which also guards the MSSP console's delegations, rule packs, overrides and client mapping and is
-- not in the permissions catalog, so a custom role (the vCIO role) could not be given it: the page said "Permission denied: mssp:manage". vcio:assess is exactly those routes under
-- /vcio-risk-scoring that write. Nobody loses anything and nothing needs backfilling: mssp:manage IMPLIES vcio:assess in app/core/security.py (IMPLIED_BY, used by permission_in, which every
-- check goes through). This migration only adds the name to the permissions catalog so a custom role can be given it on its own. It is idempotent.
-- ============================================================

INSERT INTO permissions (name, description, category) VALUES
    ('vcio:assess', 'Start, answer, fill in and delete Client Risk Score assessments (not the rest of the MSSP console)', 'vcio')
ON CONFLICT (name) DO NOTHING;
