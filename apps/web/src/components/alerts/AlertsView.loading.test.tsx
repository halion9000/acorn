import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const list = vi.hoisted(() => vi.fn());
const params = vi.hoisted(() => ({ current: new URLSearchParams('') }));
vi.mock('next/navigation', () => ({ useSearchParams: () => params.current }));
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  alertsApi: { list: (...a: unknown[]) => list(...a) },
  connectorsApi: { list: async () => ({ connectors: [] }) },
  msspApi: { listChildren: async () => [] },
}));
vi.mock('./EntityRiskQueue', () => ({ EntityRiskQueue: () => null }));
vi.mock('./InvestigationRail', () => ({ InvestigationRail: () => null }));
vi.mock('@/components/saved-views/SavedViewsBar', () => ({ SavedViewsBar: () => null }));

import { AlertsView } from './AlertsView';

const alert = (n: number) => ({ id: `a${n}`, title: `Alert ${n}`, description: '', severity: 'high', status: 'new', source: 'huntress', tenantId: 't', riskScore: 5, createdAt: '2026-11-10T09:00:00Z' });
const summary = { total: 3, critical: 0, high: 3, unresolved: 3, noTicket: 3 };

function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AlertsView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  list.mockReset();
  params.current = new URLSearchParams('');
});

describe('the alert list while it loads', () => {
  it('shows placeholder rows, not a spinner, until the first answer arrives, then the alerts', async () => {
    let answer: (v: unknown) => void = () => {};
    list.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    show();
    const loading = await screen.findByTestId('alerts-loading');
    expect(loading).toHaveAttribute('aria-label', 'Loading alerts');
    expect(loading.children).toHaveLength(8);
    answer({ alerts: [alert(1)], total: 1, summary });
    expect(await screen.findByText('Alert 1')).toBeInTheDocument();
    expect(screen.queryByTestId('alerts-loading')).toBeNull();
  });
});
