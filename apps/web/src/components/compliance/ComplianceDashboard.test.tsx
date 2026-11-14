import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ dashboard: vi.fn(), setEnabled: vi.fn(), enabled: vi.fn() }));
vi.mock('@/lib/api', () => ({
  apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null),
  complianceDashboardApi: api,
  msspApi: { listChildren: async () => [] },
}));
const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { ComplianceDashboard } from './ComplianceDashboard';
import { arcs } from './Donut';

const health = (over: Record<string, unknown> = {}) => ({ healthy: 25, at_risk: 14, unhealthy: 83, not_tested: 34, total: 156, percent_healthy: 16, ...over });
const dash = (over: Record<string, unknown> = {}) => ({
  enabled: ['SOC2'],
  health: health(),
  by_framework: [{ framework: 'SOC2', health: health() }],
  risks: { critical: 1, high: 2, medium: 3, low: 4, total: 10 },
  action_items: Array.from({ length: 7 }, (_, i) => ({ kind: 'evidence_expired', name: `SOC2 CC1.${i}: control ${i}`, event: 'Evidence expired', owner: i === 0 ? 'Hal' : null, due: '2026-09-10T00:00:00Z', link: '/compliance/soc2' })),
  generated_at: '2026-11-14T12:00:00Z',
  ...over,
});

function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <ComplianceDashboard />
    </SWRConfig>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  authFetch.mockReset();
  authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ report: { tests: { total: 163, passing: 51, failing: 93, not_evaluated: 19 } } }) });
  api.dashboard.mockResolvedValue(dash());
  api.setEnabled.mockResolvedValue({ enabled: ['SOC2', 'HIPAA'], available: [] });
  window.history.replaceState(null, '', '/compliance');
});

describe('arcs', () => {
  it('splits the ring by share, leaves out empty parts, and draws nothing for a total of zero', () => {
    const out = arcs([{ value: 1, color: 'a' }, { value: 0, color: 'b' }, { value: 3, color: 'c' }]);
    expect(out.map((a) => a.color)).toEqual(['a', 'c']);
    expect(out[1]!.offset).toBeCloseTo(out[0]!.length);
    expect(arcs([{ value: 0, color: 'a' }])).toEqual([]);
  });
});

describe('ComplianceDashboard', () => {
  it('shows the three rings with their counts: the control tests, control health and risk levels', async () => {
    show();
    expect(await screen.findByTestId('card-health')).toHaveTextContent('16%');
    expect(screen.getByTestId('card-health')).toHaveTextContent('83 Unhealthy');
    expect(screen.getByTestId('card-health')).toHaveTextContent('34 Not tested');
    expect(await screen.findByTestId('card-testing')).toHaveTextContent('31%');
    expect(screen.getByTestId('card-testing')).toHaveTextContent('93 Failing');
    expect(screen.getByTestId('card-risks')).toHaveTextContent('10');
    expect(screen.getByTestId('card-risks')).toHaveTextContent('1 Critical');
  });

  it('lists every available framework with a switch, the ones on switched on, more than one allowed', async () => {
    api.dashboard.mockResolvedValue(dash({ enabled: ['SOC2', 'HIPAA'] }));
    show();
    const box = await screen.findByTestId('framework-toggles');
    const switches = within(box).getAllByRole('switch');
    expect(switches).toHaveLength(6);
    expect(within(box).getByRole('switch', { name: 'SOC 2 Type II on' })).toHaveAttribute('aria-checked', 'true');
    expect(within(box).getByRole('switch', { name: 'HIPAA Security Rule on' })).toHaveAttribute('aria-checked', 'true');
    expect(within(box).getByRole('switch', { name: 'PCI DSS v4.0 on' })).toHaveAttribute('aria-checked', 'false');
  });

  it('turning one on sends the whole set that should be on, and loads the dashboard again', async () => {
    show();
    const box = await screen.findByTestId('framework-toggles');
    await userEvent.click(within(box).getByRole('switch', { name: 'HIPAA Security Rule on' }));
    await waitFor(() => expect(api.setEnabled).toHaveBeenCalledWith('', ['SOC2', 'HIPAA']));
    await waitFor(() => expect(api.dashboard).toHaveBeenCalledTimes(2));
    await userEvent.click(within(box).getByRole('switch', { name: 'SOC 2 Type II on' }));
    await waitFor(() => expect(api.setEnabled).toHaveBeenLastCalledWith('', []));
  });

  it('with no framework on it says to turn one on, and shows no health ring', async () => {
    api.dashboard.mockResolvedValue(dash({ enabled: [], health: null, by_framework: [], action_items: [] }));
    show();
    expect(await screen.findByTestId('health-empty')).toHaveTextContent('Turn on a framework above');
    expect(screen.getByTestId('action-items-empty')).toBeTruthy();
  });

  it('pages the action items five at a time, with the owner and the due date, linking to where each is', async () => {
    show();
    const box = await screen.findByTestId('action-items');
    await waitFor(() => expect(within(box).getAllByRole('row')).toHaveLength(6));
    expect(within(box).getByRole('link', { name: 'SOC2 CC1.0: control 0' })).toHaveAttribute('href', '/compliance/soc2');
    expect(box).toHaveTextContent('Hal');
    expect(box).toHaveTextContent('2026-09-10');
    expect(screen.getByTestId('action-pager')).toHaveTextContent('1 - 5 of 7 items');
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByTestId('action-pager')).toHaveTextContent('6 - 7 of 7 items');
    expect(within(box).getAllByRole('row')).toHaveLength(3);
    expect((screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the reason when the API refuses, and asks for the client named in the address', async () => {
    window.history.replaceState(null, '', '/compliance?client=c9');
    api.dashboard.mockRejectedValue(new Error('Client not found'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Client not found');
    await waitFor(() => expect(api.dashboard).toHaveBeenCalledWith('c9'));
    expect(screen.getByTestId('testing-empty')).toHaveTextContent('not set up for this client');
  });
});
