-- Migration 209: ThreatMate invoice lines are checked against Billable assets, not Internal assets.
--
-- Internal assets is only the devices ThreatMate sees (0 for a client whose ThreatMate covers users), while ThreatMate bills on its billing meter (devices plus billable users), which CORE reports as
-- "Billable assets" (the count the former Rewst billing page used; Tecovas: 2,354 against HaloPSA's 2,352). A line whose mapping is exactly the old default (the one count, Internal assets) is moved;
-- a line a person pointed at anything else is left alone. Idempotent.

BEGIN;

UPDATE billing_item_map
   SET counted = '[{"source": "threatmate", "item": "Billable assets"}]'::jsonb,
       updated_at = now()
 WHERE invoice_item ILIKE '%threatmate%'
   AND counted = '[{"source": "threatmate", "item": "Internal assets"}]'::jsonb;

COMMIT;
