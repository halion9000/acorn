import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { RealtimeStatus } from '@/lib/realtime';

const channel = vi.hoisted(() => ({ current: { last: null as unknown, status: 'closed' as string, problem: null as string | null, step: null as unknown } }));
vi.mock('@/lib/realtime', () => ({ useRealtimeChannel: () => channel.current }));
const stored = vi.hoisted(() => ({ rows: [] as unknown[], fail: false }));
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  alertsApi: { list: () => (stored.fail ? Promise.reject(new Error('down')) : Promise.resolve({ alerts: stored.rows })) },
}));

import { LiveFeedPanel, statusToLabel } from './LiveFeedPanel';

// An empty feed used to be labelled "Demo" with a tooltip saying "Realtime service unreachable or no events received yet — showing demo data". No demo events
// were ever shown (that code had been removed), so the claim was false, and "Demo" hid the difference between "connected, nothing yet" and "service down".
function alert(id: string, over: Record<string, unknown> = {}) {
  return { type: 'alert', timestamp: new Date().toISOString(), payload: { alert: { id, title: `Alert ${id}`, severity: 'high', source: 'edr', ...over } } };
}

function setChannel(status: RealtimeStatus, last: unknown = null, extra: { problem?: string | null; step?: unknown } = {}) {
  channel.current = { last, status, problem: extra.problem ?? null, step: extra.step ?? null };
}

beforeEach(() => {
  setChannel('closed');
  stored.rows = [];
  stored.fail = false;
});

describe('statusToLabel', () => {
  const cases: [RealtimeStatus, boolean, string, string][] = [
    ['open', true, 'Live', 'live'],
    ['open', false, 'Waiting', 'waiting'],
    ['connecting', false, 'Connecting…', 'reconnect'],
    ['connecting', true, 'Connecting…', 'reconnect'],
    ['closing', true, 'Reconnecting…', 'reconnect'],
    ['closed', true, 'Reconnecting…', 'reconnect'],
    ['error', true, 'Reconnecting…', 'reconnect'],
    ['closing', false, 'Offline', 'offline'],
    ['closed', false, 'Offline', 'offline'],
    ['error', false, 'Offline', 'offline'],
  ];
  it.each(cases)('%s, events received: %s -> %s', (status, hasReal, label, tone) => {
    const pill = statusToLabel(status, hasReal);
    expect(pill.label).toBe(label);
    expect(pill.tone).toBe(tone);
    expect(pill.hint.length).toBeGreaterThan(5);
  });

  it('never calls anything "Demo", and says nothing about demo data', () => {
    for (const status of ['connecting', 'open', 'closing', 'closed', 'error'] as RealtimeStatus[]) {
      for (const hasReal of [true, false]) {
        const pill = statusToLabel(status, hasReal);
        expect(`${pill.label} ${pill.hint}`).not.toMatch(/demo|seeded|sample/i);
      }
    }
  });
});

describe('LiveFeedPanel', () => {
  it('says the service is unreachable, and shows no events and no demo claim, when it is down', () => {
    setChannel('closed');
    const { container } = render(<LiveFeedPanel />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByText('The realtime service is unreachable.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/demo|seeded|sample/i);
    expect(container.querySelectorAll('.truncate').length).toBe(0);
    expect(screen.getByText('Offline').getAttribute('title')).toBe('The realtime service is unreachable. (WebSocket: closed)');
  });

  it('says it is connected and waiting, which is different from being down', () => {
    setChannel('open');
    const { container } = render(<LiveFeedPanel />);
    expect(screen.getByText('Waiting')).toBeInTheDocument();
    expect(screen.getByText('No events yet.')).toBeInTheDocument();
    expect(screen.queryByText('The realtime service is unreachable.')).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/demo/i);
  });

  it('shows a real event with its severity and source, and goes Live', () => {
    setChannel('open', alert('a1', { title: 'Impossible travel for jdoe', severity: 'critical', source: 'entra-id' }));
    render(<LiveFeedPanel />);
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('Impossible travel for jdoe')).toBeInTheDocument();
    expect(screen.getByText('CRIT')).toBeInTheDocument();
    expect(screen.getByText(/entra-id/)).toBeInTheDocument();
    expect(screen.queryByText('No events yet.')).not.toBeInTheDocument();
  });

  it('does not show the service\'s own "connected" frame as a security event', () => {
    setChannel('open', { type: 'connected', tenantId: 't1', channel: 'alerts' });
    render(<LiveFeedPanel />);
    expect(screen.queryByText('Security event received')).not.toBeInTheDocument();
    expect(screen.getByText('No events yet.')).toBeInTheDocument();
  });

  it('names the tool that sent a forwarded alert and the device, not "Generic Generic JSON"', () => {
    setChannel('open', alert('a2', { title: "Device 'FS2' is offline", source: 'Generic Generic JSON', hostname: 'FS2', raw_event: { source: 'ninjaone' } }));
    render(<LiveFeedPanel />);
    expect(screen.getByText(/NinjaOne\s+· FS2 · /)).toBeInTheDocument();
    expect(screen.queryByText(/Generic Generic JSON/)).not.toBeInTheDocument();
  });

  it("keeps the alert's own source when no sender is named", () => {
    setChannel('open', alert('a3', { source: 'edr', raw_event: {} }));
    render(<LiveFeedPanel />);
    expect(screen.getByText(/edr · /)).toBeInTheDocument();
  });

  it('keeps the events it has, and says it is reconnecting, if the connection drops after events arrived', () => {
    setChannel('open', alert('a1', { title: 'First real event' }));
    const { rerender } = render(<LiveFeedPanel />);
    setChannel('closed', alert('a1', { title: 'First real event' }));
    rerender(<LiveFeedPanel />);
    expect(screen.getByText('Reconnecting…')).toBeInTheDocument();
    expect(screen.getByText('First real event')).toBeInTheDocument();
  });

  it('does not show the same alert twice, and keeps only the 12 most recent', () => {
    setChannel('open', alert('dup', { title: 'Same alert' }));
    const { rerender, container } = render(<LiveFeedPanel />);
    setChannel('open', alert('dup', { title: 'Same alert' }));
    rerender(<LiveFeedPanel />);
    expect(screen.getAllByText('Same alert').length).toBe(1);
    for (let i = 0; i < 15; i += 1) {
      setChannel('open', alert(`e${i}`, { title: `Event ${i}` }));
      rerender(<LiveFeedPanel />);
    }
    expect(container.querySelectorAll('.truncate').length).toBe(12);
    expect(screen.getByText('Event 14')).toBeInTheDocument();
    expect(screen.queryByText('Same alert')).not.toBeInTheDocument();
  });
});

describe('LiveFeedPanel while it cannot connect', () => {
  it('says which step it is stuck on and which try it is', () => {
    setChannel('connecting', null, { step: { name: 'ticket', attempt: 3 } });
    render(<LiveFeedPanel />);
    expect(screen.getByTestId('live-feed-step')).toHaveTextContent('Asking the server for a connection ticket (try 3)');
  });

  it('names the socket step too, and shows the reason a try failed', () => {
    setChannel('connecting', null, { step: { name: 'socket', attempt: 1 }, problem: 'The live connection did not open within 10 seconds.' });
    render(<LiveFeedPanel />);
    expect(screen.getByTestId('live-feed-step')).toHaveTextContent('Opening the live connection (try 1)');
    expect(screen.getByTestId('live-feed-problem')).toHaveTextContent('did not open within 10 seconds');
  });

  it('shows neither once it is connected', () => {
    setChannel('open', null, { step: null, problem: null });
    render(<LiveFeedPanel />);
    expect(screen.queryByTestId('live-feed-step')).toBeNull();
    expect(screen.queryByTestId('live-feed-problem')).toBeNull();
  });
});

describe('LiveFeedPanel earlier alerts', () => {
  const row = (id: string, title: string) => ({ id, title, severity: 'low', source: 'Generic JSON', createdAt: new Date().toISOString(), rawEvent: { source: 'huntress' }, device: 'PC-1' });

  it('fills a quiet feed with the newest stored alerts, labelled as earlier and not as live', async () => {
    stored.rows = [row('a1', 'Old alert one'), row('a2', 'Old alert two')];
    setChannel('open');
    render(<LiveFeedPanel />);
    expect(await screen.findByText('Old alert one')).toBeInTheDocument();
    expect(screen.getByText('Old alert two')).toBeInTheDocument();
    expect(screen.getByTestId('live-feed-earlier')).toBeInTheDocument();
    expect(screen.getByText('Waiting')).toBeInTheDocument(); // still not claiming to be live
    expect(screen.queryByText('No events yet.')).toBeNull();
  });

  it('replaces them with live events as soon as one arrives', async () => {
    stored.rows = [row('a1', 'Old alert one')];
    setChannel('open', alert('live1', { title: 'Brand new alert' }));
    render(<LiveFeedPanel />);
    expect(await screen.findByText('Brand new alert')).toBeInTheDocument();
    expect(screen.queryByText('Old alert one')).toBeNull();
    expect(screen.queryByTestId('live-feed-earlier')).toBeNull();
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('stays empty and still works when the stored alerts cannot be read', async () => {
    stored.fail = true;
    setChannel('open');
    render(<LiveFeedPanel />);
    expect(await screen.findByText('No events yet.')).toBeInTheDocument();
  });
});
