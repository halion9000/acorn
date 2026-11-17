-- Migration 201: what each vendor costs per year (Vendors page: a yearly cost field and a total by category).
--
-- Null means no amount entered. Idempotent.

BEGIN;

ALTER TABLE vendors ADD COLUMN IF NOT EXISTS annual_spend NUMERIC(12, 2);

COMMIT;
