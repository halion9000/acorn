-- Migration 142: each install of a remote tool on a device, with where it is installed and which server it belongs to.
--
-- device_remote_tools held one row per tool per device. Some tools are installed once per server they connect to (ScreenConnect names the server in the program name and the folder:
-- "ScreenConnect Client (798cebdb8316a8ff)"), so one device can hold your own and someone else's side by side. The key now includes instance_id ('' for a tool that has no such thing),
-- and the program name and install folder are kept so the page can show where it is. Existing rows keep their key (instance_id '').
--
-- Idempotent.

BEGIN;

ALTER TABLE device_remote_tools ADD COLUMN IF NOT EXISTS instance_id  VARCHAR(40)  NOT NULL DEFAULT '';
ALTER TABLE device_remote_tools ADD COLUMN IF NOT EXISTS program      VARCHAR(255);
ALTER TABLE device_remote_tools ADD COLUMN IF NOT EXISTS install_path VARCHAR(500);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
        WHERE c.relname = 'device_remote_tools' AND i.indisprimary AND a.attname = 'instance_id'
    ) THEN
        ALTER TABLE device_remote_tools DROP CONSTRAINT IF EXISTS device_remote_tools_pkey;
        ALTER TABLE device_remote_tools ADD PRIMARY KEY (tenant_id, hostname_key, tool_key, instance_id);
    END IF;
END $$;

COMMIT;
