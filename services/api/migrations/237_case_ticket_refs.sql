-- Migration 237: a case keeps the HaloPSA tickets it is linked to (ticket_refs), so every case can be tied to a ticket: the one an alert's ticket rule opened, one a person linked, or one opened from the case. Idempotent.
--
-- Each entry: {"system": "halopsa", "id": "<ticket number>", "added_by": "<who or what>", "added_at": "<time>"}.
-- Cases that already exist get the tickets of their alerts (the numbers CORE matched or a person entered on the alert), so the link is not lost for old cases.

ALTER TABLE aisoc_cases ADD COLUMN IF NOT EXISTS ticket_refs JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE aisoc_cases c
SET ticket_refs = sub.refs
FROM (
    SELECT c2.id,
           jsonb_agg(DISTINCT jsonb_build_object('system', 'halopsa', 'id', t->>'id', 'added_by', 'alert', 'added_at', to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))) AS refs
    FROM aisoc_cases c2
    JOIN alerts a ON a.id = ANY (c2.alert_ids) AND a.tenant_id = c2.tenant_id
    CROSS JOIN LATERAL (
        SELECT e AS t
        FROM jsonb_array_elements(
            (CASE WHEN jsonb_typeof(a.enrichment_data -> 'manual_tickets') = 'array' THEN a.enrichment_data -> 'manual_tickets' ELSE '[]'::jsonb END)
            || (CASE WHEN jsonb_typeof(a.enrichment_data -> 'tickets') = 'array' THEN a.enrichment_data -> 'tickets' ELSE '[]'::jsonb END)
        ) e
    ) tk
    WHERE c2.ticket_refs = '[]'::jsonb
      AND jsonb_typeof(a.enrichment_data) = 'object'
      AND jsonb_typeof(t) = 'object'
      AND COALESCE(t->>'id', '') <> ''
      AND COALESCE(t->>'system', 'halopsa') = 'halopsa'
    GROUP BY c2.id
) sub
WHERE c.id = sub.id AND c.ticket_refs = '[]'::jsonb;
