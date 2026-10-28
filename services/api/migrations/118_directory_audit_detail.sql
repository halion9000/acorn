-- What changed in a directory audit entry (the group a person was added to, the property and its old and new value, what made the change), sent by CORE from Microsoft's own record.
-- Entries stored before this have none. Safe to run again.
ALTER TABLE directory_audit_events ADD COLUMN IF NOT EXISTS detail text;
