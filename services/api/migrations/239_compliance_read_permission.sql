-- Migration 239: compliance:read, the read-only permission for the compliance records (the answer library, questionnaires, access reviews, vendors and the automated tests).
--
-- Nobody loses anything and nothing needs backfilling: reports:read IMPLIES compliance:read in app/core/security.py (permission_in), which every check goes through; a holder of compliance:read alone (CORE's key, for the
-- four compliance skills of the agents) can read those records and nothing else under reports. Listed here so the role editor shows it. Idempotent.
INSERT INTO permissions (name, description, category) VALUES
    ('compliance:read', 'Read the compliance records: the answer library, questionnaires, access reviews, vendors and the automated tests (nothing else under reports)', 'compliance')
ON CONFLICT (name) DO NOTHING;
