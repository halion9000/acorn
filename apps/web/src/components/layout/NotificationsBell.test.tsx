import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';
import type { Alert } from '@/lib/api';

const listMock = vi.fn();
const fetchMock = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => fetchMock(...a) }));
vi.mock('@/lib/api', () => ({ alertsApi: { list: (...a: unknown[]) => listMock(...a) } }));
vi.mock('next/link', () => ({ default: ({ children, href, onClick, ...rest }: { children: React.ReactNode; href: string; onClick?: () => void; 'data-testid'?: string }) => <a href={href} onClick={onClick} data-testid={rest['data-testid']}>{children}</a> }));

import { NotificationsBell, billingLinesOff, needsAttention } from './NotificationsBell';

const alert = (id: string, severity: string, createdAt: string, clientName?: string) => ({ id, title: `Alert ${id}`, severity, createdAt, clientName }) as unknown as Alert;
const wrap = () => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}><NotificationsBell /></SWRConfig>);

beforeEach(() => {
  listMock.mockReset();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: false, status: 403, json: async () => ({}) });
});

describe('needsAttention', () => {
  it('merges critical and high newest first and caps the list', () => {
    const out = needsAttention([alert('c1', 'critical', '2026-10-15T01:00:00Z')], [alert('h1', 'high', '2026-10-15T02:00:00Z'), alert('h2', 'high', '2026-10-14T01:00:00Z')], 2);
    expect(out.map((a) => a.id)).toEqual(['h1', 'c1']);
  });
});

describe('the notifications bell', () => {
  it('opens a panel with the newest critical/high alerts, each a link, and closes again', async () => {
    listMock.mockImplementation(async (f: { severity: string }) =>
      f.severity === 'critical'
        ? { alerts: [alert('c1', 'critical', '2026-10-15T01:00:00Z', 'Acme')], total: 3 }
        : { alerts: [alert('h1', 'high', '2026-10-15T02:00:00Z')], total: 5 },
    );
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('Alert c1')).toBeTruthy();
    expect(screen.getByText('3 critical, 5 high, not yet picked up')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Alert c1/ }).getAttribute('href')).toBe('/alerts/c1');
    expect(screen.getByRole('link', { name: 'View all alerts' }).getAttribute('href')).toBe('/alerts');
    expect(screen.getByTestId('bell-dot')).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('says so, and shows no red dot, when nothing needs attention', async () => {
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('No new critical or high alerts.')).toBeTruthy();
    expect(screen.queryByTestId('bell-dot')).toBeNull();
  });
});

describe('billing lines in the bell', () => {
  const row = (client_id: string, difference: number, note_state = 'none') => ({ client_id, difference, note_state });
  const rows = { rows: [row('a', 2), row('a', -1), row('b', 5, 'accepted'), row('c', 0), row('d', 3, 'stale')] };

  it('counts the lines that disagree and are not accepted, and the clients they are for', () => {
    expect(billingLinesOff(rows.rows)).toEqual({ lines: 3, clients: 2 });
    expect(billingLinesOff([])).toEqual({ lines: 0, clients: 0 });
  });

  it('shows how many billed lines have been off for two weeks, with a link to the page and an amber dot', async () => {
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => rows });
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('3 billed lines off for 14+ days')).toBeTruthy();
    expect(screen.getByText(/across 2 clients; not accepted yet/)).toBeTruthy();
    expect(screen.getByTestId('bell-billing').getAttribute('href')).toBe('/settings/billing');
    expect(screen.getByTestId('bell-dot-billing')).toBeTruthy();
    expect(screen.queryByTestId('bell-dot')).toBeNull();
    expect(String(fetchMock.mock.calls[0][0])).toContain('min_days=14');
  });

  it('shows nothing about billing when there is none, or when the reader may not see it', async () => {
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    const user = userEvent.setup();
    const first = wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('No new critical or high alerts.')).toBeTruthy();
    expect(screen.queryByTestId('bell-billing')).toBeNull();
    expect(screen.queryByTestId('bell-dot-billing')).toBeNull();
    first.unmount();
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ({ rows: [row('a', 0), row('b', 4, 'accepted')] }) });
    wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('No new critical or high alerts.')).toBeTruthy();
    expect(screen.queryByTestId('bell-billing')).toBeNull();
  });
});
