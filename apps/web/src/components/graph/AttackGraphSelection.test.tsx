import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

// A stand-in for cytoscape that remembers the handlers, so a click on a node can be simulated without a canvas.
const fake = vi.hoisted(() => {
  const handlers: Record<string, (evt: unknown) => void> = {};
  const chain = () => {
    const c: Record<string, unknown> = {};
    for (const m of ['removeClass', 'addClass', 'not', 'unselect', 'select', 'neighborhood', 'closedNeighborhood']) c[m] = () => c;
    c.empty = () => true;
    c.forEach = () => undefined;
    return c;
  };
  const core = Object.assign(
    (_selectorOrHandler: unknown) => undefined,
    {},
  );
  const cy = {
    on: (event: string, selectorOrHandler: unknown, maybe?: (evt: unknown) => void) => {
      const key = typeof selectorOrHandler === 'string' ? `${event}:${selectorOrHandler}` : event;
      handlers[key] = (maybe ?? selectorOrHandler) as (evt: unknown) => void;
    },
    elements: chain,
    nodes: chain,
    getElementById: chain,
    animate: () => undefined,
    destroy: () => undefined,
    fit: () => undefined,
    zoom: () => 1,
    width: () => 100,
    height: () => 100,
    layout: () => ({ run: () => undefined }),
  };
  void core;
  return { handlers, cy };
});
vi.mock('cytoscape', () => ({ __esModule: true, default: Object.assign(() => fake.cy, { use: vi.fn() }) }));
vi.mock('cytoscape-fcose', () => ({ __esModule: true, default: vi.fn() }));
vi.mock('next/link', () => ({ __esModule: true, default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a> }));

const overview = {
  generatedAt: '2026-11-21T12:00:00Z',
  nodes: [
    { id: 'host:D68HM3L3', label: 'D68HM3L3', kind: 'host', riskScore: 80, severity: 'high', attributes: { alerts: 3 } },
    { id: 'user:dan@acme.com', label: 'dan@acme.com', kind: 'user', riskScore: 40, severity: 'medium', attributes: { alerts: 1 } },
    { id: 'alert:a1', label: 'Impossible travel', kind: 'alert', riskScore: 80, severity: 'high', attributes: { alert_id: 'uuid-1' } },
    { id: 'ip:1.2.3.4', label: '1.2.3.4', kind: 'ip', riskScore: 30, severity: 'low' },
  ],
  edges: [
    { id: 'e1', source: 'host:D68HM3L3', target: 'user:dan@acme.com', label: 'together' },
    { id: 'e2', source: 'alert:a1', target: 'host:D68HM3L3', label: 'names' },
    { id: 'e3', source: 'ip:1.2.3.4', target: 'alert:a1', label: 'names' },
  ],
};

vi.mock('@/lib/api', () => ({
  __esModule: true,
  graphApi: { getOverview: async () => overview, getMitreCoverage: async () => ({ tactics: [], cells: [], generatedAt: '2026-11-21T12:00:00Z' }) },
  msspApi: { listChildren: async () => [] },
}));

import { AttackGraphView, connectionsOf } from './AttackGraphView';

afterEach(cleanup);

const tap = (id: string) => act(() => fake.handlers['tap:node']({ target: { id: () => id } }));

describe('the attack graph side panel', () => {
  it('lists what a node connects to, riskiest first, and nothing it is not joined to', () => {
    expect(connectionsOf(overview as never, 'host:D68HM3L3').map((n) => n.label)).toEqual(['Impossible travel', 'dan@acme.com']);
    expect(connectionsOf(overview as never, 'ip:1.2.3.4').map((n) => n.label)).toEqual(['Impossible travel']);
    expect(connectionsOf(overview as never, 'nope')).toEqual([]);
  });

  it('offers to go to the device, the identity or the alert behind the clicked node, and none for an address', async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <AttackGraphView />
      </SWRConfig>,
    );
    await screen.findByTestId('graph-side-panel');
    await vi.waitFor(() => expect(fake.handlers['tap:node']).toBeDefined());

    tap('host:D68HM3L3');
    const panel = screen.getByTestId('graph-side-panel');
    expect(within(panel).getByRole('link', { name: /Go to device/ })).toHaveAttribute('href', '/devices?search=D68HM3L3');
    expect(within(panel).getByText('Connected to (2)')).toBeInTheDocument();

    tap('user:dan@acme.com');
    expect(within(panel).getByRole('link', { name: /Go to identity/ })).toHaveAttribute('href', '/identities?search=dan%40acme.com');

    tap('alert:a1');
    expect(within(panel).getByRole('link', { name: /Go to alert/ })).toHaveAttribute('href', '/alerts/uuid-1');

    tap('ip:1.2.3.4');
    expect(within(panel).queryByRole('link')).toBeNull();

    // A connection in the panel selects that node.
    await userEvent.click(within(panel).getByRole('button', { name: /Impossible travel/ }));
    expect(within(panel).getByRole('link', { name: /Go to alert/ })).toBeInTheDocument();
  });
});
