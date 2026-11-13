-- ============================================================
-- Migration 176: a View and a Manage permission for each area of Settings
-- ============================================================
-- The routes behind eight areas of Settings shared one blanket pair, settings:read and settings:write, so Retention, the HaloPSA ticket status, the AI key, standing approvals and the rest could
-- only be given together. Each area now has its own pair, listed here so the role editor shows them: Workspace, Deployment and AI, Clients, Automation, Tickets, Data, Reports, Security tools.
-- Nobody loses anything and nothing needs backfilling: settings:read implies every View and settings:write every Manage (IMPLIED_BY in app/core/security.py, used by permission_in, which every check
-- goes through), and Manage implies View of its own area. Roles, People, Audit and Connectors already had permissions of their own and keep them. Idempotent.
-- ============================================================

INSERT INTO permissions (name, description, category) VALUES
    ('settings_workspace:view', 'See the workspace settings: the organisation''s name, branding and locale', 'settings'),
    ('settings_workspace:manage', 'Change the workspace settings', 'settings'),
    ('settings_deployment:view', 'See Deployment and AI: the deployment mode, the air-gap policy, the AI provider and its status', 'settings'),
    ('settings_deployment:manage', 'Change Deployment and AI: the deployment mode, the air-gap bundle and the AI key', 'settings'),
    ('settings_clients:view', 'See the client settings: client status links and the Client Risk Score scoring', 'settings'),
    ('settings_clients:manage', 'Change the client settings: make and end client status links, and change how the Client Risk Score is calculated', 'settings'),
    ('settings_automation:view', 'See Automation: the autonomy agreement, standing approvals and the auto-close threshold', 'settings'),
    ('settings_automation:manage', 'Change Automation: standing approvals and the auto-close threshold', 'settings'),
    ('settings_tickets:view', 'See the ticket settings: the HaloPSA status a resolved incident moves its ticket to', 'settings'),
    ('settings_tickets:manage', 'Change the ticket settings', 'settings'),
    ('settings_data:view', 'See Data: retention and log parsers', 'settings'),
    ('settings_data:manage', 'Change Data: retention and log parsers', 'settings'),
    ('settings_reports:view', 'Use the report builder checks', 'settings'),
    ('settings_reports:manage', 'Change report builder settings', 'settings'),
    ('settings_security:view', 'See the security tool settings: posture destinations', 'settings'),
    ('settings_security:manage', 'Run posture and exposure scans, load the knowledge base and run purple-team simulations', 'settings')
ON CONFLICT (name) DO NOTHING;
