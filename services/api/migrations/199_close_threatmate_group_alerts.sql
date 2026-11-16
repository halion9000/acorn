-- Migration 199: close the group alerts for two ThreatMate checks that no longer raise one.
--
-- "New deep and dark web findings for this client" and "Serious vulnerabilities on this client's internet-facing addresses" were one alert each for a whole client, saying "N findings". They are replaced by one
-- alert per dark web finding (CORE) and ThreatMate's own alert for each address or domain. The old group alerts would stay open for ever (nothing resolves a check that no longer alerts), so the ones still
-- open are closed here, once. Only alerts raised by the A.C.O.R.N checks for these two rules; nothing else is touched. Idempotent.

BEGIN;

UPDATE alerts
SET status = 'closed',
    updated_at = now()
WHERE connector_type = 'aisoc-checks'
  AND rule_id IN ('check:threatmate_deep_dark_web', 'check:threatmate_external_exposure')
  AND status NOT IN ('resolved', 'closed', 'false_positive', 'fp', 'suppressed', 'stale');

COMMIT;
