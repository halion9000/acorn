-- Migration 232: the Metrics datasets CORE sends now include meeting hours and the HaloPSA user roles.
--
-- The check on metric_datasets.key listed the five datasets of the first build, so a send of 'meetings-weekly' (or 'halo-user-roles') was refused by the database (HTTP 422, "A value is not allowed"). Idempotent.

BEGIN;

ALTER TABLE metric_datasets DROP CONSTRAINT IF EXISTS metric_datasets_key;
ALTER TABLE metric_datasets ADD CONSTRAINT metric_datasets_key
    CHECK (key IN ('staff-weekly', 'ticket-detail', 'invoice-lines', 'dialpad-weekly', 'm365-roles', 'meetings-weekly', 'halo-user-roles'));

COMMIT;
