import { describe, expect, it } from 'vitest';

import type { GraphNode } from '@/lib/api';
import { nodeLink } from './graphLinks';

const node = (over: Partial<GraphNode>): GraphNode => ({ id: 'x', label: 'x', kind: 'host', ...over });

describe('where a clicked node leads', () => {
  it('opens a host as a device, a user as an identity and an alert as an alert', () => {
    expect(nodeLink(node({ kind: 'host', label: 'D68HM3L3' }))).toEqual({ href: '/devices?search=D68HM3L3', label: 'Go to device' });
    expect(nodeLink(node({ kind: 'user', label: 'dan@acme.com' }))).toEqual({ href: '/identities?search=dan%40acme.com', label: 'Go to identity' });
    expect(nodeLink(node({ kind: 'alert', id: 'alert:abc', attributes: { alert_id: '1234-uuid' } }))).toEqual({ href: '/alerts/1234-uuid', label: 'Go to alert' });
  });

  it('reads the alert from the node id when the attribute is missing, and sends a technique to the coverage page', () => {
    expect(nodeLink(node({ kind: 'alert', id: 'alert:abc' }))?.href).toBe('/alerts/abc');
    expect(nodeLink(node({ kind: 'technique', label: 'T1059' }))).toEqual({ href: '/detection/coverage', label: 'Go to MITRE coverage' });
  });

  it('carries the client picked on the graph to the device and identity pages, not to an alert', () => {
    expect(nodeLink(node({ kind: 'host', label: 'PC-1' }), 'c-1')?.href).toBe('/devices?search=PC-1&client=c-1');
    expect(nodeLink(node({ kind: 'user', label: 'a b' }), 'c-1')?.href).toBe('/identities?search=a%20b&client=c-1');
    expect(nodeLink(node({ kind: 'alert', id: 'alert:z' }), 'c-1')?.href).toBe('/alerts/z');
  });

  it('has no page for an address, a domain, a hash or a process', () => {
    for (const kind of ['ip', 'domain', 'hash', 'process'] as const) expect(nodeLink(node({ kind }))).toBeNull();
  });
});
