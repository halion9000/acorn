import { describe, expect, it } from 'vitest';
import type { EnvDevice } from '@/lib/api';
import { MAX_NODES, MAX_PER_ROW, buildMap, tierOf } from './networkMap';

const dev = (name: string, role: string | null, kind: string, links: { name: string; port?: string; remote_port?: string }[] = []): EnvDevice => ({
  id: name,
  hostname: name,
  kind,
  role,
  online: true,
  tools: ['auvik'],
  links: links.map((l) => ({ name: l.name, port: l.port ?? null, remote_port: l.remote_port ?? null, speed: null })),
  missing: [],
  pushable: [],
});

describe('tierOf', () => {
  it('puts firewalls on top, switches next, access points below, and everything else last', () => {
    expect(tierOf({ role: 'firewall', kind: 'network' })).toBe(0);
    expect(tierOf({ role: 'l3switch', kind: 'network' })).toBe(1);
    expect(tierOf({ role: 'accesspoint', kind: 'network' })).toBe(2);
    expect(tierOf({ role: 'workstation', kind: 'computer' })).toBe(3);
    expect(tierOf({ role: null, kind: 'network' })).toBe(1);
  });
});

describe('buildMap', () => {
  const devices = [
    dev('fw', 'firewall', 'network', [{ name: 'sw', port: 'LAN', remote_port: 'Gi1' }]),
    dev('sw', 'switch', 'network', [{ name: 'fw', port: 'Gi1', remote_port: 'LAN' }, { name: 'ap', port: 'Gi2' }, { name: 'pc', port: 'Gi3' }]),
    dev('ap', 'accesspoint', 'network'),
    dev('pc', 'workstation', 'computer'),
    dev('lonely', 'switch', 'network'),
  ];

  it('draws each cable once even though both ends report it, with every linked device below its parent tier, and leaves out an unlinked device', () => {
    const m = buildMap(devices);
    expect(m.edges).toHaveLength(3);
    const at = (id: string) => m.nodes.find((n) => n.id === id)!;
    expect(at('fw').y).toBeLessThan(at('sw').y);
    expect(at('sw').y).toBeLessThan(at('ap').y);
    expect(at('ap').y).toBeLessThan(at('pc').y);
    expect(m.nodes.map((n) => n.id)).not.toContain('lonely');
    expect(m.edges.find((e) => e.from === 'fw' || e.to === 'fw')?.label).toMatch(/LAN|Gi1/);
  });

  it('ignores a link to a name it does not know and a link to itself, and draws nothing when no device is linked', () => {
    expect(buildMap([dev('a', 'switch', 'network', [{ name: 'ghost' }, { name: 'a' }])]).nodes).toEqual([]);
  });

  it('matches neighbour names without regard to case or spaces', () => {
    const m = buildMap([dev('Core-SW', 'switch', 'network', [{ name: ' fw ' }]), dev('FW', 'firewall', 'network')]);
    expect(m.edges).toHaveLength(1);
  });

  it('wraps a long row, keeps every node inside the drawing, and caps the number of devices drawn', () => {
    const pcs = Array.from({ length: 25 }, (_, i) => dev(`pc${i}`, 'workstation', 'computer'));
    const big = buildMap([dev('sw', 'switch', 'network', pcs.map((p) => ({ name: p.hostname }))), ...pcs]);
    const rows = new Set(big.nodes.filter((n) => n.tier === 3).map((n) => n.y));
    expect(rows.size).toBe(Math.ceil(25 / MAX_PER_ROW));
    for (const n of big.nodes) expect(n.x).toBeGreaterThan(0), expect(n.x).toBeLessThan(big.width);
    const many = Array.from({ length: MAX_NODES + 30 }, (_, i) => dev(`d${i}`, 'workstation', 'computer'));
    const capped = buildMap([dev('hub', 'switch', 'network', many.map((p) => ({ name: p.hostname }))), ...many]);
    expect(capped.nodes.length).toBe(MAX_NODES);
    expect(capped.hidden).toBe(31);
  });
});
