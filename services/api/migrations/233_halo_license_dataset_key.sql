-- Migration 233: the Metrics datasets CORE sends now include the HaloPSA licenses and which invoice lines carry them (the Billing sync Linked column). Idempotent.

BEGIN;

ALTER TABLE metric_datasets DROP CONSTRAINT IF EXISTS metric_datasets_key;
ALTER TABLE metric_datasets ADD CONSTRAINT metric_datasets_key
    CHECK (key IN ('staff-weekly', 'ticket-detail', 'invoice-lines', 'dialpad-weekly', 'm365-roles', 'meetings-weekly', 'halo-user-roles', 'halo-licenses'));

COMMIT;
