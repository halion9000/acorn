import { describe, expect, it } from 'vitest';
import type { DeviceRow } from '@/lib/api';
import { inventoryLine, inventoryLines, kindCounts } from '@/lib/deviceInventory';

const dev = (over: Partial<DeviceRow>): DeviceRow => ({
  id: 'd', tenant_id: 't', client_name: 'Acme', hostname: 'PC-1', serial_number: 'SN1', os: 'Windows 11', os_version: '23H2', manufacturer: 'Dell', model: 'Latitude 5440', ip_addresses: ['10.0.0.5'],
  last_seen: '2026-11-16T10:00:00Z', first_seen: '2026-01-01T00:00:00Z', sources: [{ vendor: 'ninjaone', name: null, last_seen: '2026-11-16T10:00:00Z' }, { vendor: 'huntress', name: null, last_seen: '' }, { vendor: 'ninjaone', name: null, last_seen: '' }],
  in_master: true, kind: 'computer', ...over,
});

describe('the device inventory lines', () => {
  it('writes what a person wants on paper: name, kind, make and model, serial, system, addresses, tools once each and the day it was last online', () => {
    expect(inventoryLine(dev({ last_online: '2026-11-15T08:00:00Z' }))).toEqual({
      hostname: 'PC-1', kind: 'Computer', makeModel: 'Dell Latitude 5440', serial: 'SN1', os: 'Windows 11 23H2', addresses: '10.0.0.5', tools: 'huntress, ninjaone', lastOnline: '2026-11-15',
    });
  });
  it('copes with what is missing: no serial, no make, no online time, three addresses at most', () => {
    const l = inventoryLine(dev({ serial_number: null, manufacturer: null, model: null, os: null, os_version: null, kind: 'network', ip_addresses: ['1.1.1.1', '2.2.2.2', '3.3.3.3', '4.4.4.4'], online: true }));
    expect([l.serial, l.makeModel, l.os, l.kind, l.addresses, l.lastOnline]).toEqual(['', '', '', 'Network device', '1.1.1.1, 2.2.2.2, 3.3.3.3', 'online now']);
    expect(inventoryLine(dev({ kind: undefined })).kind).toBe('Computer');
  });
  it('sorts by name without regard to case and leaves out a device a person hid', () => {
    const lines = inventoryLines([dev({ hostname: 'zeta' }), dev({ hostname: 'Alpha' }), dev({ hostname: 'beta' }), dev({ hostname: 'hidden-one', hidden_since: '2026-11-01T00:00:00Z' })]);
    expect(lines.map((l) => l.hostname)).toEqual(['Alpha', 'beta', 'zeta']);
  });
  it('counts the kinds in words, biggest first, singular for one', () => {
    const lines = inventoryLines([dev({ hostname: 'a' }), dev({ hostname: 'b' }), dev({ hostname: 'sw', kind: 'network' }), dev({ hostname: 'cam', kind: 'camera' }), dev({ hostname: 'x', kind: 'other' })]);
    expect(kindCounts(lines)).toBe('2 computers, 1 camera, 1 network device, 1 other');
    expect(kindCounts([])).toBe('');
  });
});
