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

import { NotificationsBell, approvalsLine, becFinishedLine, billingLinesOff, needsAttention } from './NotificationsBell';

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

describe('CORE approvals in the bell', () => {
  const okJson = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

  it('says nothing when none are waiting, and describes the one closest to expiring when some are', () => {
    expect(approvalsLine([])).toBeNull();
    expect(approvalsLine([{ role: 'cipher', summary: 'Close case 7', days_left: 1 }, { role: 'jax', summary: 'Escalate 12', days_left: 5 }])).toEqual({
      title: '2 approvals waiting in CORE',
      detail: 'cipher: Close case 7 (expires in 1 day). Answer in the CORE app.',
    });
    expect(approvalsLine([{ role: 'jax', summary: 'x', days_left: 0 }])?.detail).toContain('expires today');
    expect(approvalsLine([{ role: 'jax', summary: 'x', days_left: 4 }])?.title).toBe('1 approval waiting in CORE');
  });

  it('shows an amber dot and a row in the panel, below the alerts, when CORE reported waiting approvals', async () => {
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    fetchMock.mockImplementation(async (url: string) =>
      String(url).includes('core-approvals') ? okJson({ reported: true, items: [{ role: 'cipher', summary: 'Close case 7', days_left: 2 }] }) : { ok: false, status: 403, json: async () => ({}) },
    );
    const user = userEvent.setup();
    wrap();
    expect(await screen.findByTestId('bell-dot-approvals')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    const row = await screen.findByTestId('bell-approvals');
    expect(row.textContent).toContain('1 approval waiting in CORE');
    expect(row.textContent).toContain('cipher: Close case 7 (expires in 2 days)');
  });

  it('shows neither when CORE has not reported, the list is empty, or the person may not read it', async () => {
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    const user = userEvent.setup();
    for (const answer of [okJson({ reported: false, items: [] }), okJson({ reported: true, items: [] }), { ok: false, status: 403, json: async () => ({}) }]) {
      fetchMock.mockImplementation(async (url: string) => (String(url).includes('core-approvals') ? answer : { ok: false, status: 403, json: async () => ({}) }));
      const view = wrap();
      await user.click(screen.getByRole('button', { name: 'Open notifications' }));
      await screen.findByText('No new critical or high alerts.');
      expect(screen.queryByTestId('bell-dot-approvals')).toBeNull();
      expect(screen.queryByTestId('bell-approvals')).toBeNull();
      view.unmount();
    }
  });

  it('a critical alert still wins the dot', async () => {
    listMock.mockImplementation(async (f: { severity: string }) => (f.severity === 'critical' ? { alerts: [alert('c1', 'critical', '2026-10-15T01:00:00Z')], total: 1 } : { alerts: [], total: 0 }));
    fetchMock.mockImplementation(async (url: string) => (String(url).includes('core-approvals') ? okJson({ items: [{ role: 'jax', summary: 's', days_left: 3 }] }) : { ok: false, status: 403, json: async () => ({}) }));
    wrap();
    expect(await screen.findByTestId('bell-dot')).toBeTruthy();
    expect(screen.queryByTestId('bell-dot-approvals')).toBeNull();
  });
});

describe('finished BEC searches in the bell', () => {
  it('words a finished search from the rating CIPP gave, and a failed one as not finished, and never says clean', () => {
    expect(becFinishedLine({ id: '1', client_name: 'Acme', email: 'p@x.com', status: 'done', level: 'High', ticket_id: '4242' })).toEqual({
      title: 'BEC search for p@x.com finished',
      detail: 'CIPP rates it High · Acme · ticket 4242',
    });
    expect(becFinishedLine({ id: '2', client_name: '', email: 'p@x.com', status: 'done', level: null }).detail).toBe('CIPP gave no rating');
    expect(becFinishedLine({ id: '3', client_name: 'Acme', email: 'p@x.com', status: 'failed' }).title).toBe('BEC search for p@x.com did not finish');
  });

  it('shows a blue dot and a row for a finished search, and the dot goes once the bell has been opened', async () => {
    window.localStorage.clear();
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    fetchMock.mockImplementation(async (url: string) =>
      String(url).includes('bec/finished')
        ? { ok: true, status: 200, json: async () => ({ items: [{ id: 'b1', client_name: 'Acme', email: 'p@x.com', status: 'done', level: 'High', ticket_id: null }] }) }
        : { ok: false, status: 403, json: async () => ({}) },
    );
    const user = userEvent.setup();
    wrap();
    expect(await screen.findByTestId('bell-dot-bec')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(await screen.findByText('BEC search for p@x.com finished')).toBeTruthy();
    expect(screen.queryByTestId('bell-dot-bec')).toBeNull();
  });

  it('shows nothing about BEC when the reader may not see it', async () => {
    window.localStorage.clear();
    listMock.mockResolvedValue({ alerts: [], total: 0 });
    const user = userEvent.setup();
    wrap();
    await user.click(screen.getByRole('button', { name: 'Open notifications' }));
    expect(screen.queryByTestId('bell-bec')).toBeNull();
    expect(screen.queryByTestId('bell-dot-bec')).toBeNull();
  });
});
