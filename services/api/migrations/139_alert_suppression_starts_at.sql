-- Migration 139: a start time for alert suppression rules, so a rule can be a maintenance window (hide a client's alerts from a start to an end).
--
-- starts_at NULL means the rule applies from the moment it is made (every rule before this migration). A maintenance window is a client rule whose signature is "window:all-types"; it never hides
-- critical alerts and the application limits it to 72 hours. Idempotent.

BEGIN;

ALTER TABLE alert_suppressions ADD COLUMN IF NOT EXISTS starts_at TIMESTAMPTZ;

COMMIT;
