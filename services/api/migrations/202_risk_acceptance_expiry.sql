-- Migration 202: an end date for an accepted risk (Risk Management: risk acceptance with an expiry and a reminder).
--
-- Only meaningful when the risk's treatment is accept; null means no end date. The Compliance overview lists accepted risks whose acceptance has ended or ends within 30 days. Idempotent.

BEGIN;

ALTER TABLE risk_register_items ADD COLUMN IF NOT EXISTS accepted_until DATE;

COMMIT;
