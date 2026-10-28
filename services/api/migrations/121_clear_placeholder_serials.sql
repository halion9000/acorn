-- Some tools report a serial number that is an unfilled template ("$(DEFAULT_STRING)", "%SERIAL%", "{SerialNumber}", "<unknown>"), not a serial. The serial is what joins one machine across tools,
-- and a client can hold only one device per serial, so every machine that reported the template was folded into ONE device (seen: a device with 31 source records under 9 different names).
-- New reports of such values now count as no serial. The devices already folded together cannot be told apart again from what is stored, and a device is only a view of what the tools report,
-- so those devices are removed (their source records, "not a duplicate" marks and hides go with them) and the next sync rebuilds them correctly, one device per tool record, joined by name or by
-- a real serial. Safe to run again: once removed, nothing matches.
DELETE FROM devices
 WHERE serial_number ~ '^(\$\(.*\)|%.*%|\{.*\}|<.*>)$';
