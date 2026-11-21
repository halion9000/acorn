-- Migration 236: the permission to sign in as another person of the organization (Settings > People > Impersonate), listed so the role editor shows it. Tenant admins hold it; a custom role can be given it. Idempotent.
INSERT INTO permissions (name, description, category) VALUES
    ('users:impersonate', 'Impersonate another person: see the console exactly as they see it, with their permissions, until you end it (every action is logged with your name)', 'users')
ON CONFLICT (name) DO NOTHING;
