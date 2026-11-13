-- ============================================================
-- Migration 175: devices.alt_serials, the other serial numbers of one machine
-- ============================================================
-- One virtual machine can carry two serials: an Azure or Hyper-V VM has the host's in NinjaOne and the guest operating system's in Huntress, ScreenConnect and ThreatMate. The two lines were
-- never joined (a serial is the only automatic match across tools) and a person could not merge them (two serials are refused as two machines). A merge on a person's word ("same machine") now
-- keeps the removed line's serial here, on the device that stays, so that a later report carrying that serial finds this device instead of splitting a new line off. Empty for every device
-- until someone says so. Idempotent.
-- ============================================================

ALTER TABLE devices ADD COLUMN IF NOT EXISTS alt_serials TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_devices_alt_serials ON devices USING GIN (alt_serials);
