-- The Microsoft 365 tenant id a tool reports for a client (Petra, Huntress, ...). Two tools that name the same Microsoft tenant are the same customer, so a client with an unmapped alias is linked to the
-- client tenant another tool's alias with the same id already maps to. Optional: tools that do not report one leave it empty.
ALTER TABLE client_aliases ADD COLUMN IF NOT EXISTS microsoft_tenant_id TEXT;
CREATE INDEX IF NOT EXISTS client_aliases_ms_tenant_idx ON client_aliases (tenant_id, microsoft_tenant_id) WHERE microsoft_tenant_id IS NOT NULL;
