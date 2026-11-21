import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DatasetHistoryView } from './DatasetHistoryView';

const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

afterEach(() => {
  cleanup();
  authFetch.mockReset();
});

describe('data history', () => {
  it('lists the data sets, their versions newest first, and opens one with its checksum check', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.endsWith('/version/7')) return ok({ id: 7, key: 'csat', received_at: '2026-11-19T10:00:00Z', sha256: 'a'.repeat(64), bytes: 20, payload: { score: 4.5 }, verified: true });
      if (url.includes('/dataset-history/csat')) return ok([{ id: 9, received_at: '2026-11-20T10:00:00Z', sha256: 'b'.repeat(64), bytes: 2048 }, { id: 7, received_at: '2026-11-19T10:00:00Z', sha256: 'a'.repeat(64), bytes: 20 }]);
      return ok([{ key: 'csat', versions: 2, first: '2026-11-19T10:00:00Z', latest: '2026-11-20T10:00:00Z' }]);
    });
    const user = userEvent.setup();
    render(<DatasetHistoryView />);
    await user.selectOptions(await screen.findByLabelText('Data set'), 'csat');
    expect(await screen.findAllByTestId('version-row')).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: 'Open version 7' }));
    expect(await screen.findByText(/still matches the checksum/)).toBeInTheDocument();
    expect(screen.getByTestId('version-body')).toHaveTextContent('"score": 4.5');
  });

  it('says so when nothing is saved yet, and when the permission is missing', async () => {
    authFetch.mockImplementation(() => ok([]));
    render(<DatasetHistoryView />);
    expect(await screen.findByTestId('no-datasets')).toBeInTheDocument();
    cleanup();
    authFetch.mockImplementation(() => Promise.resolve({ ok: false, status: 403, json: () => Promise.resolve({}) }));
    render(<DatasetHistoryView />);
    expect(await screen.findByText(/needs the reports permission/)).toBeInTheDocument();
  });

  it('warns when a stored copy no longer matches its checksum', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.includes('/version/')) return ok({ id: 1, key: 'k', received_at: '2026-11-19T10:00:00Z', sha256: 'c'.repeat(64), bytes: 2, payload: {}, verified: false });
      if (url.includes('/dataset-history/k')) return ok([{ id: 1, received_at: '2026-11-19T10:00:00Z', sha256: 'c'.repeat(64), bytes: 2 }]);
      return ok([{ key: 'k', versions: 1, first: '2026-11-19T10:00:00Z', latest: '2026-11-19T10:00:00Z' }]);
    });
    const user = userEvent.setup();
    render(<DatasetHistoryView />);
    await user.selectOptions(await screen.findByLabelText('Data set'), 'k');
    await user.click(await screen.findByRole('button', { name: 'Open version 1' }));
    expect(await screen.findByText(/no longer matches/)).toBeInTheDocument();
  });
});
