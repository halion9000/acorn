-- Migration 107: a check that does not apply to a client (no firewall, no domain controller).
--
-- client_check_acceptances.not_applicable: set when a person says the check does not apply to the client at all, as opposed to accepting a risk that does apply. Such a row has no end date. It is left out of
-- the client's score like an accepted one, and the page shows "Not applicable" instead of "Accepted". Idempotent.

BEGIN;

ALTER TABLE client_check_acceptances ADD COLUMN IF NOT EXISTS not_applicable BOOLEAN NOT NULL DEFAULT false;

COMMIT;
