import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren: async () => [{ id: 'c1', name: 'Acme Dental' }] } }));

import { EventSearchView, exportQuery, searchQuery } from './EventSearchView';

const row = (id: number, over: Record<string, unknown> = {}) => ({ id, client_id: null, source: 'halopsa', kind: 'ticket.created', event_time: '2026-11-18T09:00:00Z', pulled_at: '2026-11-19T00:00:00Z', external_id: `t${id}:created`, preview: `Ticket ${id}`, ...over });
const answer = (rows: unknown[], next: number | null = null) => ({ ok: true, status: 200, json: () => Promise.resolve({ rows, next_before: next, sources: ['dialpad', 'halopsa'] }) });

afterEach(() => {
  cleanup();
  authFetch.mockReset();
});

describe('event search', () => {
  it('asks only for the filters that are set, and a date range covers whole days', () => {
    expect(searchQuery({ client: '', source: '', kind: '', q: '', since: '', until: '' })).toBe('');
    const q = new URLSearchParams(searchQuery({ client: 'c1', source: 'halopsa', kind: ' ticket.closed ', q: ' printer ', since: '2026-11-01', until: '2026-11-30', before: 40 }));
    expect(Object.fromEntries(q)).toEqual({ client_id: 'c1', source: 'halopsa', kind: 'ticket.closed', q: 'printer', since: '2026-11-01T00:00:00Z', until: '2026-12-01T00:00:00Z', before: '40' });
    expect(searchQuery({ client: '', source: '', kind: '', q: '', since: 'soon', until: '' })).toBe('');
  });

  it('lists the events newest first, opens one whole, and loads older ones when there are more', async () => {
    authFetch.mockImplementation((url: string) => {
      if (/\/events\/2$/.test(url)) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ...row(2), payload: { summary: 'Ticket 2', client: 'Acme' } }) });
      return Promise.resolve(url.includes('before=2') ? answer([row(1)]) : answer([row(3), row(2)], 2));
    });
    render(<EventSearchView />);
    expect(await screen.findAllByTestId('event-row')).toHaveLength(2);
    await userEvent.click(screen.getByRole('button', { name: 'Open event t2:created' }));
    expect(await screen.findByTestId('event-raw')).toHaveTextContent('"client": "Acme"');
    await userEvent.click(screen.getByRole('button', { name: 'Older events' }));
    await waitFor(() => expect(screen.getAllByTestId('event-row')).toHaveLength(3));
    expect(screen.queryByRole('button', { name: 'Older events' })).toBeNull();
  });

  it('searches with the text typed and says when nothing matches', async () => {
    authFetch.mockImplementation((url: string) => Promise.resolve(url.includes('q=nothing') ? answer([]) : answer([row(1)])));
    render(<EventSearchView />);
    await screen.findAllByTestId('event-row');
    await userEvent.type(screen.getByLabelText('Text'), 'nothing');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByTestId('no-events')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Source')).getAllByRole('option').map((o) => o.textContent)).toEqual(['All sources', 'dialpad', 'halopsa']);
  });

  it('says when the permission is missing', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 403, json: () => Promise.resolve({}) });
    render(<EventSearchView />);
    expect(await screen.findByText(/needs the reports permission/)).toBeInTheDocument();
  });

  it('builds the export address with the client and only the filters that are set', () => {
    expect(Object.fromEntries(new URLSearchParams(exportQuery({ client: 'c1', source: '', since: '', until: '' })))).toEqual({ client_id: 'c1' });
    expect(Object.fromEntries(new URLSearchParams(exportQuery({ client: 'c1', source: '', since: '', until: '', format: 'csv' })))).toEqual({ client_id: 'c1', format: 'csv' });
    expect(Object.fromEntries(new URLSearchParams(exportQuery({ client: 'c1', source: 'halopsa', since: '2026-11-01', until: '2026-11-30' })))).toEqual({ client_id: 'c1', source: 'halopsa', since: '2026-11-01T00:00:00Z', until: '2026-12-01T00:00:00Z' });
  });

  it('exports one client as a zip when a client is chosen, and says so when the permission or the size stops it', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.includes('/events/export')) return Promise.resolve({ ok: true, status: 200, blob: () => Promise.resolve(new Blob(['zip'])) });
      return Promise.resolve(answer([row(1)]));
    });
    const created: string[] = [];
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => (created.push('x'), 'blob:x');
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <EventSearchView />
      </SWRConfig>,
    );
    await screen.findAllByTestId('event-row');
    const button = screen.getByRole('button', { name: 'Export this client' });
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');
    await userEvent.click(button);
    await waitFor(() => expect(created).toHaveLength(1));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/events/export?client_id=c1');
    authFetch.mockImplementation((url: string) => Promise.resolve(url.includes('/events/export') ? { ok: false, status: 413, json: () => Promise.resolve({ detail: 'That is 300000 events; export a shorter date range' }) } : answer([row(1)])));
    await userEvent.click(button);
    expect(await screen.findByText(/export a shorter date range/)).toBeInTheDocument();
    authFetch.mockImplementation((url: string) => Promise.resolve(url.includes('/events/export') ? { ok: false, status: 403, json: () => Promise.resolve({}) } : answer([row(1)])));
    await userEvent.click(button);
    expect(await screen.findByText(/Exporting needs the manage permission/)).toBeInTheDocument();
  });
});
