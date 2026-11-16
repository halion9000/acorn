-- Migration 200: the sidebar section that was called "Automation" (Playbooks, File Integrity, Honeytokens, Purple Team) is now "Response & Defense"; "Automation" is a new section (Auto Tickets, Auto Scripts, HubSpot).
--
-- A role that hid "section:Automation" meant the OLD section. So that those roles keep hiding exactly the same pages, "section:Response & Defense" is added to every role that hides "section:Automation".
-- The new Automation section stays hidden for them too: it holds tools they were not shown automation for either. Roles that already hide the new name are left alone. Idempotent.

BEGIN;

UPDATE roles
SET hidden_nav = hidden_nav || '["section:Response & Defense"]'::jsonb
WHERE hidden_nav ? 'section:Automation'
  AND NOT (hidden_nav ? 'section:Response & Defense');

COMMIT;
