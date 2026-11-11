import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

describe('Alerts > Export all', () => {
  it('is offered when the filter matches more than the page shows, reads every page with the same filter, and saves them all', async () => {
    // The page shows one alert of three; an "export all" request (page size 200) gets all three.
    list.mockImplementation(async (f: { pageSize?: number }) => (f.pageSize === 200 ? { alerts: [alert(1), alert(2), alert(3)], total: 3, summary } : { alerts: [alert(1)], total: 3, summary }));
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { blobs.push(b); return 'blob:a'; }), revokeObjectURL: vi.fn() });
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    show();
    await userEvent.click(await screen.findByRole('button', { name: 'Export all 3' }));
    await waitFor(() => expect(screen.getByTestId('export-all-note')).toHaveTextContent('Saved 3 alerts.'));
    expect(names).toEqual(['alerts-all.csv']);
    const text = await blobs[0].text();
    for (const n of [1, 2, 3]) expect(text).toContain(`Alert ${n}`);
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ page: 1, pageSize: 200 }));
    click.mockRestore();
  });

  it('is not offered when the page already shows everything', async () => {
    list.mockResolvedValue({ alerts: [alert(1)], total: 1, summary: { ...summary, total: 1 } });
    show();
    await screen.findByRole('button', { name: 'Export CSV' });
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /Export all/ })).toBeNull();
  });
});
