-- Migration 128: three indexes the code from this month leans on, and the missing link from a playbook dry run to its alert.
--
-- 1. client_documents: the daily ticket prune deletes by "last touched" (the ticketing tool's date, or when it was received when it sent none). Without an index that delete read every ticket of the client. Partial, on tickets only.
-- 2. playbook_dry_runs: alert_id had no foreign key (a deleted alert left its dry runs behind for ever) and no index (deleting an alert, and asking for one alert's dry runs, read the whole table). The rows whose alert is already gone are removed
--    first, since they could never be shown and would stop the foreign key from being added.
-- 3. billing_difference_notes.client_id has ON DELETE CASCADE to tenants and no index of its own (the primary key leads with tenant_id), so removing a client read the whole table.
-- Safe to run twice.
BEGIN;

CREATE INDEX IF NOT EXISTS idx_client_documents_ticket_age
    ON client_documents (tenant_id, vendor, (coalesce(vendor_updated_at, received_at)))
    WHERE kind = 'ticket';

DELETE FROM playbook_dry_runs d WHERE NOT EXISTS (SELECT 1 FROM alerts a WHERE a.id = d.alert_id);
CREATE INDEX IF NOT EXISTS idx_playbook_dry_runs_alert ON playbook_dry_runs (alert_id);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'playbook_dry_runs_alert_id_fkey') THEN
        ALTER TABLE playbook_dry_runs ADD CONSTRAINT playbook_dry_runs_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES alerts (id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_billing_difference_notes_client ON billing_difference_notes (client_id);

COMMIT;
