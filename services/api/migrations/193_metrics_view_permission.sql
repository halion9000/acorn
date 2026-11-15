-- Migration 193: metrics:view, the read-only permission for the ticket metrics and customer satisfaction.
--
-- It guards the GET routes under /reports/ticket-metrics (tickets created and resolved, first response, by type and engineer, what is open, and customer satisfaction with customers' written comments).
-- Nobody loses anything and nothing needs backfilling: reports:read IMPLIES metrics:view in app/core/security.py (permission_in), which every check goes through (static roles, database roles, API-key
-- scopes and a `metrics:*` wildcard). This only adds the name to the permissions catalog so a custom role or an API key can be given these pages on its own. Idempotent.

INSERT INTO permissions (name, description, category) VALUES
    ('metrics:view', 'Read the ticket metrics and customer satisfaction (counts per client and the satisfaction comments customers wrote)', 'reports')
ON CONFLICT (name) DO NOTHING;
