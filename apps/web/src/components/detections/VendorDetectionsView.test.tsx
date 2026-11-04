import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ vendorDetections: vi.fn() }));
vi.mock('@/lib/api', () => ({ detectionApi: { vendorDetections: api.vendorDetections } }));

import { VendorDetectionsView, alertsHref, forResolution } from './VendorDetectionsView';

const DATA = {
  window_days: 30,
  detections: [
    { source: 'huntress', name: 'Malicious Process', count: 5, open: 2, severity: 'critical', clients: 3, last_seen: '2026-10-14T10:00:00+00:00' },
    { source: 'petra', name: 'Impossible travel', count: 1, open: 0, severity: 'medium', clients: 1, last_seen: null },
  ],
};

function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <VendorDetectionsView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  api.vendorDetections.mockReset();
});

describe('VendorDetectionsView', () => {
  it('lists what each tool detected and filters by tool', async () => {
    api.vendorDetections.mockResolvedValue(DATA);
    const user = userEvent.setup();
    show();
    const table = await screen.findByRole('table');
    expect(within(table).getByText('Malicious Process')).toBeInTheDocument();
    expect(within(table).getByText('Impossible travel')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Petra \(1\)/ }));
    expect(within(screen.getByRole('table')).queryByText('Malicious Process')).not.toBeInTheDocument();
    expect(within(screen.getByRole('table')).getByText('Impossible travel')).toBeInTheDocument();
  });

  it('filters by severity and sorts the most serious first', async () => {
    api.vendorDetections.mockResolvedValue({
      window_days: 30,
      detections: [
        { source: 'huntress', name: 'Low one', count: 9, open: 1, severity: 'low', clients: 1, last_seen: '2026-10-14T10:00:00+00:00' },
        { source: 'huntress', name: 'Critical one', count: 2, open: 1, severity: 'critical', clients: 1, last_seen: '2026-10-13T10:00:00+00:00' },
        { source: 'petra', name: 'High one', count: 4, open: 0, severity: 'high', clients: 2, last_seen: null },
      ],
    });
    const user = userEvent.setup();
    show();
    await screen.findByRole('table');
    const names = () => screen.getAllByRole('row').map((r) => r.textContent ?? '').filter((t) => /one/.test(t));
    expect(names().map((t) => t.match(/(Critical|High|Low) one/)?.[0])).toEqual(['Critical one', 'High one', 'Low one']);

    await user.click(screen.getByRole('button', { name: /^high \(1\)/ }));
    expect(screen.getByText('High one')).toBeInTheDocument();
    expect(screen.queryByText('Low one')).not.toBeInTheDocument();
    expect(screen.queryByText('Critical one')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^All$/ }));
    expect(screen.getByText('Low one')).toBeInTheDocument();
  });

  it('sorts a column when its header is clicked and filters by detection text and a minimum', async () => {
    api.vendorDetections.mockResolvedValue({
      window_days: 30,
      detections: [
        { source: 'huntress', name: 'Few', count: 2, open: 0, severity: 'low', clients: 1, last_seen: null },
        { source: 'huntress', name: 'Many', count: 50, open: 0, severity: 'low', clients: 1, last_seen: null },
        { source: 'huntress', name: 'Some', count: 10, open: 0, severity: 'low', clients: 1, last_seen: null },
      ],
    });
    const user = userEvent.setup();
    show();
    await screen.findByRole('table');
    const order = () => screen.getAllByRole('row').map((r) => r.textContent ?? '').filter((t) => /Few|Many|Some/.test(t)).map((t) => t.match(/Few|Many|Some/)?.[0]);
    await user.click(within(screen.getByRole('columnheader', { name: /Alerts/ })).getByRole('button'));
    expect(order()).toEqual(['Few', 'Some', 'Many']);
    await user.click(within(screen.getByRole('columnheader', { name: /Alerts/ })).getByRole('button'));
    expect(order()).toEqual(['Many', 'Some', 'Few']);

    await user.type(screen.getByLabelText('Minimum Alerts'), '10');
    expect(order()).toEqual(['Many', 'Some']);
    await user.type(screen.getByLabelText('Filter Detection'), 'man');
    expect(order()).toEqual(['Many']);
    await user.type(screen.getByLabelText('Minimum Alerts'), '00');
    expect(screen.getByText('Nothing matches these filters.')).toBeInTheDocument();
  });

  it('says plainly when nothing has fired', async () => {
    api.vendorDetections.mockResolvedValue({ window_days: 30, detections: [] });
    show();
    expect(await screen.findByText(/No vendor detections yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Connectors/i })).toHaveAttribute('href', '/settings/connectors');
  });

  it('shows an error with a retry instead of an empty table', async () => {
    api.vendorDetections.mockRejectedValueOnce(new Error('boom'));
    show();
    expect(await screen.findByText(/Could not load vendor detections/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it('opens the alerts behind a detection from its name or its count', async () => {
    api.vendorDetections.mockResolvedValue(DATA);
    show();
    const table = await screen.findByRole('table');
    const expected = '/alerts?status=all&source=huntress&q=Malicious%20Process';
    expect(within(table).getByRole('link', { name: 'Malicious Process' })).toHaveAttribute('href', expected);
    expect(within(table).getByRole('link', { name: '5' })).toHaveAttribute('href', expected);
  });

  it('builds the address safely for names with spaces, symbols and quotes', () => {
    expect(alertsHref({ source: 'threatmate', name: 'A&B "x" = 100%?' })).toBe('/alerts?status=all&source=threatmate&q=A%26B%20%22x%22%20%3D%20100%25%3F');
  });

  it('shows all, only unresolved or only resolved detections, with the counts and the links of that state', async () => {
    api.vendorDetections.mockResolvedValue(DATA);
    const user = userEvent.setup();
    show();
    const table = await screen.findByRole('table');
    expect(screen.getByRole('button', { name: 'all (6)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'unresolved (2)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'resolved (4)' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'unresolved (2)' }));
    expect(within(table).queryByText('Impossible travel')).toBeNull(); // nothing open
    expect(within(table).getByRole('link', { name: '2' })).toHaveAttribute('href', '/alerts?status=open&source=huntress&q=Malicious%20Process');

    await user.click(screen.getByRole('button', { name: 'resolved (4)' }));
    expect(within(table).getByRole('link', { name: '3' })).toHaveAttribute('href', '/alerts?status=resolved&source=huntress&q=Malicious%20Process');
    expect(within(table).getByText('Impossible travel')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'all (6)' }));
    expect(within(table).getByRole('link', { name: '5' })).toHaveAttribute('href', '/alerts?status=all&source=huntress&q=Malicious%20Process');
  });

  it('forResolution counts resolved as alerts less open, leaves out detections with none, and never goes negative', () => {
    const rows = [{ count: 5, open: 2 }, { count: 1, open: 0 }, { count: 3, open: 3 }, { count: 2, open: 9 }];
    expect(forResolution(rows, 'all')).toEqual(rows);
    expect(forResolution(rows, 'unresolved').map((r) => r.count)).toEqual([2, 3, 9]);
    expect(forResolution(rows, 'resolved').map((r) => r.count)).toEqual([3, 1]);
  });
});
