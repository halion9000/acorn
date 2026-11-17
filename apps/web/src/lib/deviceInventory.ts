/**
 * A client's device inventory as a printable list: one row per device with what a person wants on paper (name, kind, make and model, serial number, operating system, addresses, which tools see it and when it
 * was last online), sorted by name, plus the counts by kind for the page header. Pure over the device rows the Devices page already reads.
 */
import type { DeviceRow } from '@/lib/api';

export interface InventoryLine {
  hostname: string;
  kind: string;
  makeModel: string;
  serial: string;
  os: string;
  addresses: string;
  tools: string;
  lastOnline: string;
}

const KIND_LABEL: Record<string, string> = { computer: 'Computer', network: 'Network device', camera: 'Camera', other: 'Other' };
const day = (iso: string | null | undefined): string => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : '');

/** One printable line for a device (pure). */
export function inventoryLine(d: DeviceRow): InventoryLine {
  const tools = [...new Set((d.sources ?? []).map((s) => s.vendor).filter(Boolean))].sort();
  return {
    hostname: d.hostname,
    kind: KIND_LABEL[d.kind ?? 'computer'] ?? 'Other',
    makeModel: [d.manufacturer, d.model].filter(Boolean).join(' '),
    serial: d.serial_number ?? '',
    os: [d.os, d.os_version].filter(Boolean).join(' '),
    addresses: (d.ip_addresses ?? []).slice(0, 3).join(', '),
    tools: tools.join(', '),
    lastOnline: day(d.last_online) || (d.online === true ? 'online now' : ''),
  };
}

/** The inventory lines, devices a person hid left out, sorted by name without regard to case (pure). */
export function inventoryLines(devices: DeviceRow[]): InventoryLine[] {
  return devices
    .filter((d) => !d.hidden_since)
    .map(inventoryLine)
    .sort((a, b) => a.hostname.localeCompare(b.hostname, undefined, { sensitivity: 'base' }));
}

/** How many of each kind, as "12 computers, 3 network devices" (pure). */
export function kindCounts(lines: InventoryLine[]): string {
  const n = new Map<string, number>();
  for (const l of lines) n.set(l.kind, (n.get(l.kind) ?? 0) + 1);
  const plural = (k: string, c: number): string => (c === 1 ? k.toLowerCase() : k === 'Other' ? 'other' : `${k.toLowerCase()}s`);
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k, c]) => `${c} ${plural(k, c)}`).join(', ');
}
