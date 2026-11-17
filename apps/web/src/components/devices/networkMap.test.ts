import { describe, expect, it } from 'vitest';
import type { EnvDevice } from '@/lib/api';
import { MAX_NODES, MAX_PER_ROW, buildMap, classOf, tierOf } from './networkMap';

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

describe('classOf', () => {
  it('tells a firewall, router, switch, controller and wireless access point apart, by the role the tool gives', () => {
    const c = (role: string | null, kind = 'network') => classOf({ role, kind });
    expect([c('firewall'), c('UTM'), c('securityAppliance')]).toEqual(['firewall', 'firewall', 'firewall']);
    expect([c('router'), c('modem')]).toEqual(['router', 'router']);
    expect([c('switch'), c('l3switch'), c('stack')]).toEqual(['switch', 'switch', 'switch']);
    expect([c('controller'), c('loadBalancer')]).toEqual(['controller', 'controller']);
    expect([c('accessPoint'), c('thinAccessPoint')]).toEqual(['wap', 'wap']);
  });
  it('a computer is a workstation unless its role says server or laptop, and the other kinds get their own class', () => {
    expect(classOf({ role: null, kind: 'computer' })).toBe('workstation');
    expect(classOf({ role: 'Windows Server 2022', kind: 'computer' })).toBe('server');
    expect(classOf({ role: 'MacBook Pro', kind: 'computer' })).toBe('laptop');
    expect(classOf({ role: null, kind: 'camera' })).toBe('camera');
    expect(classOf({ role: 'printer', kind: 'other' })).toBe('printer');
    expect(classOf({ role: 'VoIP phone', kind: 'other' })).toBe('phone');
    expect(classOf({ role: null, kind: 'other' })).toBe('other');
    expect(classOf({ role: null, kind: 'network' })).toBe('switch');
  });
  it('every node in a drawn map carries its class', () => {
    const m = buildMap([dev('fw', 'firewall', 'network', [{ name: 'sw' }]), dev('sw', 'switch', 'network', [{ name: 'fw' }, { name: 'ap' }, { name: 'pc' }]), dev('ap', 'accesspoint', 'network', [{ name: 'sw' }]), dev('pc', null, 'computer', [{ name: 'sw' }])]);
    expect(Object.fromEntries(m.nodes.map((n) => [n.id, n.cls]))).toEqual({ fw: 'firewall', sw: 'switch', ap: 'wap', pc: 'workstation' });
  });
});
