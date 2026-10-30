import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), listChildren: vi.fn(), exportCsv: vi.fn() }));
vi.mock('@/lib/api', () => ({ identitiesApi: { list: api.list, detail: api.detail, exportCsv: api.exportCsv }, msspApi: { listChildren: api.listChildren } }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { IdentitiesView, ticketAge } from './IdentitiesView';

const person = (over: Record<string, unknown> = {}) => ({
  key: 'c1:amy@acme.com',
  client_id: 'c1',
  client_name: 'Acme',
  email: 'amy@acme.com',
  display_name: 'Amy Adams',
  kind: 'user',
  enabled: true,
  admin: false,
  licensed: true,
  mfa: 'covered',
  mfa_methods: null,
  tools: ['cipp', 'dropsuite'],
  sources: [],
  open_alerts: 0,
  top_severity: null,
  ...over,
});
const list = (items: unknown[], over: Record<string, unknown> = {}) => ({
  summary: { total: items.length, with_alerts: 1, without_mfa: 2, admins: 1, disabled: 0, in_one_tool: 3, tools: { cipp: 5, dropsuite: 2, 'datto-saas': 1 } },
  items,
  total: items.length,
  page: 1,
  page_size: 50,
  pages: 1,
  ...over,
});
const lastQuery = () => api.list.mock.calls.at(-1)![0] as Record<string, unknown>;

function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <IdentitiesView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme' }, { id: 'c2', name: 'Beta' }]);
  api.list.mockResolvedValue(list([person(), person({ key: 'c1:bob@acme.com', email: 'bob@acme.com', display_name: null, mfa: 'none', tools: ['dropsuite'], open_alerts: 3, top_severity: 'high', admin: true, enabled: false })]));
});

describe('the Identities page', () => {
  it('lists each person once with their tools as logos, multi-factor state and alerts', async () => {
    show();
    const rows = await screen.findAllByTestId('identity-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Amy Adams');
    expect(rows[0]).toHaveTextContent('amy@acme.com');
    expect(within(rows[0]).getAllByRole('img').map((i) => i.getAttribute('title'))).toEqual(['CIPP', 'Dropsuite']);
    expect(rows[0]).toHaveTextContent('Covered');
    expect(rows[1]).toHaveTextContent('bob@acme.com');
    expect(rows[1]).toHaveTextContent('None');
    expect(rows[1]).toHaveTextContent('3');
    expect(rows[1]).toHaveTextContent('high');
    expect(rows[1]).toHaveTextContent('admin');
    expect(rows[1]).toHaveTextContent('disabled');
    expect(screen.getByTestId('identities-total')).toHaveTextContent('2');
  });

  it('filters by account state: enabled only, disabled only, or both, and the Disabled accounts tile does the same as the disabled choice', async () => {
    show();
    await screen.findAllByTestId('identity-row');
    await userEvent.selectOptions(screen.getByLabelText('Account state'), 'enabled');
    await waitFor(() => expect([lastQuery().enabled, lastQuery().disabled]).toEqual([true, false]));
    await userEvent.selectOptions(screen.getByLabelText('Account state'), 'disabled');
    await waitFor(() => expect([lastQuery().enabled, lastQuery().disabled]).toEqual([false, true]));
    await userEvent.selectOptions(screen.getByLabelText('Account state'), '');
    await waitFor(() => expect([lastQuery().enabled, lastQuery().disabled]).toEqual([false, false]));
    await userEvent.click(screen.getByRole('button', { name: /Disabled accounts/ }));
    await waitFor(() => expect(lastQuery().disabled).toBe(true));
    expect((screen.getByLabelText('Account state') as HTMLSelectElement).value).toBe('disabled');
  });

  it('opens on the people of one client when the address names the client (the People button on Client Posture)', async () => {
    window.history.pushState({}, '', '/identities?client=c2');
    try {
      show();
      await screen.findAllByTestId('identity-row');
      await waitFor(() => expect(lastQuery().clientId).toBe('c2'));
    } finally {
      window.history.pushState({}, '', '/');
    }
  });

  it('filters by search, client, tool and multi-factor, asking the server and starting again at page 1', async () => {
    show();
    await screen.findAllByTestId('identity-row');
    await userEvent.type(screen.getByLabelText('Search people'), 'amy');
    await waitFor(() => expect(lastQuery().search).toBe('amy'));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c2');
    await waitFor(() => expect(lastQuery().clientId).toBe('c2'));
    await userEvent.selectOptions(screen.getByLabelText('Known to'), 'dropsuite');
    await waitFor(() => expect(lastQuery().source).toBe('dropsuite'));
    await userEvent.selectOptions(screen.getByLabelText('Multi-Factor'), 'none');
    await waitFor(() => expect(lastQuery().mfa).toBe('none'));
    expect(lastQuery().page).toBe(1);
  });

  it('the tiles filter too, and show the counts for everyone', async () => {
    show();
    await screen.findAllByTestId('identity-row');
    expect(screen.getByRole('button', { name: /With open alerts/ })).toHaveTextContent('1');
    await userEvent.click(screen.getByRole('button', { name: /With open alerts/ }));
    await waitFor(() => expect(lastQuery().hasAlerts).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: /Administrators/ }));
    await waitFor(() => expect(lastQuery().admin).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: /No Multi-Factor/ }));
    await waitFor(() => expect(lastQuery().mfa).toBe('none'));
    await userEvent.click(screen.getByRole('button', { name: /No Multi-Factor/ }));
    await waitFor(() => expect(lastQuery().mfa).toBeUndefined());
  });

  it('"in only one tool" needs a tool picked, and then asks for the people only that tool knows', async () => {
    show();
    await screen.findAllByTestId('identity-row');
    await userEvent.click(screen.getByRole('button', { name: /In only one tool/ }));
    expect(screen.getByText(/Pick a tool below/)).toBeInTheDocument();
    expect(lastQuery().onlyIn).toBeUndefined();
    await userEvent.selectOptions(screen.getByLabelText('Known to'), 'dropsuite');
    await waitFor(() => expect(lastQuery().onlyIn).toBe('dropsuite'));
  });

  it('sorts by the column clicked', async () => {
    show();
    await screen.findAllByTestId('identity-row');
    expect(lastQuery().sort).toBe('alerts');
    await userEvent.click(within(screen.getByRole('columnheader', { name: /Client/ })).getByRole('button'));
    await waitFor(() => expect(lastQuery().sort).toBe('client'));
    await userEvent.click(within(screen.getByRole('columnheader', { name: /Known to/ })).getByRole('button'));
    await waitFor(() => expect(lastQuery().sort).toBe('tools'));
    await userEvent.click(within(screen.getByRole('columnheader', { name: /Person/ })).getByRole('button'));
    await waitFor(() => expect(lastQuery().sort).toBe('email'));
  });

  it('a row opens to each tool\'s record, the alerts that name the person and their sign-ins', async () => {
    api.detail.mockResolvedValue({
      person: person({ sources: [{ vendor: 'cipp', external_id: '1', enabled: true, details: {} }, { vendor: 'dropsuite', external_id: '2', enabled: false, details: {} }], mfa_methods: 'authenticator' }),
      alerts: [{ id: 'a9', title: 'Impossible travel', severity: 'high', status: 'new', source: 'petra', created_at: '2026-10-22T00:00:00Z' }],
      signins: { last_30_days: 40, failed: 3, unusual: 2, countries: ['US', 'GB'], last_at: '2026-10-22T10:00:00Z' },
    });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const detail = await screen.findByTestId('identity-detail');
    expect(api.detail).toHaveBeenCalledWith('c1', 'amy@acme.com');
    expect(detail).toHaveTextContent('CIPP');
    expect(detail).toHaveTextContent('Dropsuite');
    expect(detail).toHaveTextContent('disabled');
    expect(within(detail).getByRole('link', { name: 'Impossible travel' })).toHaveAttribute('href', '/alerts/a9');
    expect(detail).toHaveTextContent('40 sign-ins, 3 failed');
    expect(detail).toHaveTextContent('From: US, GB');
    expect(detail).toHaveTextContent('authenticator');
  });

  it('a row also shows the latest tickets, sign-ins and directory changes, each only when there is something to show', async () => {
    const base = { person: person(), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } };
    api.detail.mockResolvedValue({
      ...base,
      tickets: [{ id: '101', summary: 'Cannot print', status: 'Open', opened_at: '2026-10-22T00:00:00Z', url: 'https://acme.halopsa.com/tickets?id=101', source: 'halopsa' }],
      recent_signins: [
        { at: '2026-10-22T10:00:00Z', app: 'Outlook', country: 'US', city: 'Austin', ip: '1.1.1.1', success: true, mfa: false, unusual: true },
        { at: '2026-10-22T09:00:00Z', app: null, country: null, city: null, ip: null, success: false, mfa: null, unusual: false },
      ],
      changes: [{ at: '2026-10-21T10:00:00Z', activity: 'Reset user password', actor: 'admin@acme.com', target: 'amy@acme.com', detail: null, success: true }],
    });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const detail = await screen.findByTestId('identity-detail');
    expect(within(detail).getByRole('link', { name: '#101 Cannot print' })).toHaveAttribute('href', 'https://acme.halopsa.com/tickets?id=101');
    const signins = within(detail).getByTestId('person-signins');
    expect(signins).toHaveTextContent('Outlook');
    expect(signins).toHaveTextContent('Austin, US');
    expect(signins).toHaveTextContent('no multi-factor');
    expect(signins).toHaveTextContent('flagged unusual');
    expect(signins).toHaveTextContent('unknown app');
    expect(within(detail).getByTestId('person-changes')).toHaveTextContent('Reset user password');
    expect(within(detail).getByTestId('person-changes')).toHaveTextContent('by admin@acme.com');
    expect(within(detail).getByTestId('person-changes')).not.toHaveTextContent(' on amy@acme.com');
  });

  it('copies the address to the clipboard and says so, or says plainly when the browser refuses', async () => {
    const base = { person: person(), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } };
    api.detail.mockResolvedValue(base);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const detail = await screen.findByTestId('identity-detail');
    await userEvent.click(within(detail).getByRole('button', { name: 'Copy amy@acme.com' }));
    expect(writeText).toHaveBeenCalledWith('amy@acme.com');
    expect(await within(detail).findByRole('button', { name: 'Copy amy@acme.com' })).toHaveTextContent('Copied');
    writeText.mockRejectedValue(new Error('denied'));
    await userEvent.click(within(detail).getByRole('button', { name: 'Copy amy@acme.com' }));
    expect(await within(detail).findByRole('button', { name: 'Copy amy@acme.com' })).toHaveTextContent('Could not copy');
  });

  it('says when a ticket was closed, and says nothing of it for an open ticket or an older answer', async () => {
    const base = { person: person(), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } };
    api.detail.mockResolvedValue({
      ...base,
      tickets: [
        { id: '101', summary: 'Cannot print', status: 'Closed', opened_at: '2026-10-22T00:00:00Z', closed_at: '2026-10-23T00:00:00Z', url: null, source: 'halopsa' },
        { id: '102', summary: 'Slow laptop', status: 'Open', opened_at: '2026-10-24T00:00:00Z', closed_at: null, url: null, source: 'halopsa' },
        { id: '103', summary: 'Old answer', status: 'Open', opened_at: '2026-10-25T00:00:00Z', url: null, source: 'halopsa' },
      ],
    });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const tickets = within(await screen.findByTestId('identity-detail')).getByTestId('person-tickets');
    const items = within(tickets).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent(/Closed · .* · closed .*ago/);
    expect(items[1]).not.toHaveTextContent('closed ');
    expect(items[2]).not.toHaveTextContent('closed ');
  });

  it('shows no sign-in or change sections for an older answer that has neither, and says when there are no tickets', async () => {
    api.detail.mockResolvedValue({ person: person(), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const detail = await screen.findByTestId('identity-detail');
    expect(within(detail).getByTestId('person-tickets')).toHaveTextContent('No ticket in the last 60 days names this person.');
    expect(within(detail).queryByTestId('person-signins')).toBeNull();
    expect(within(detail).queryByTestId('person-changes')).toBeNull();
  });

  it('says plainly when nobody matches, and shows an error with a retry', async () => {
    api.list.mockResolvedValueOnce(list([], { total: 0 }));
    const first = show();
    expect(await screen.findByText('No people match.')).toBeInTheDocument();
    first.unmount();
    api.list.mockRejectedValue(new Error('API 500'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the identities: API 500');
  });

  it('pages through a long list', async () => {
    api.list.mockResolvedValue(list([person()], { page: 1, pages: 3, total: 120 }));
    show();
    await screen.findAllByTestId('identity-row');
    expect(screen.getByText(/Page 1 of 3 \(120 people\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(lastQuery().page).toBe(2));
  });
});

describe('tickets on the people list', () => {
  it('shows how many tickets a person has and how long ago the newest was opened, and a dash for none', async () => {
    const opened = new Date(Date.now() - 3 * 86_400_000 - 3_600_000).toISOString();
    api.list.mockResolvedValue(list([person({ tickets: 12, last_ticket_at: opened }), person({ key: 'c1:bob@acme.com', email: 'bob@acme.com', display_name: null })]));
    show();
    const cells = await screen.findAllByTestId('tickets-cell');
    expect(cells[0]).toHaveTextContent('12');
    expect(cells[0]).toHaveTextContent('last 3 days ago');
    expect(cells[1]).toHaveTextContent('—');
  });

  it('says today, 1 day ago and N days ago', () => {
    const now = Date.parse('2026-10-28T12:00:00Z');
    expect(ticketAge('2026-10-28T01:00:00Z', now)).toBe('today');
    expect(ticketAge('2026-10-27T11:00:00Z', now)).toBe('1 day ago');
    expect(ticketAge('2026-10-16T12:00:00Z', now)).toBe('12 days ago');
    expect(ticketAge('2026-10-29T12:00:00Z', now)).toBe('today');
  });
});

describe('alerts broken up by the tool that raised them', () => {
  it('shows each person\'s open alerts as one chip per tool, with the count', async () => {
    api.list.mockResolvedValue(list([person({ open_alerts: 5, top_severity: 'high', alerts_by_source: { huntress: 3, petra: 2 } })]));
    show();
    const row = await screen.findByTestId('identity-row');
    const chips = within(within(row).getByTestId('alerts-by-source')).getAllByTitle(/open alert/);
    expect(chips.map((c) => c.getAttribute('title'))).toEqual(['3 open alerts from Huntress', '2 open alerts from Petra']);
    expect(chips[0]).toHaveTextContent('3');
    expect(row).toHaveTextContent('5');
  });

  it('an alert naming no tool shows as other', async () => {
    api.list.mockResolvedValue(list([person({ open_alerts: 1, alerts_by_source: { other: 1 } })]));
    show();
    expect(await screen.findByTitle('1 open alert from an unnamed tool')).toBeInTheDocument();
  });

  it('can be filtered to people with an alert from one tool, offering the tools that have alerts', async () => {
    api.list.mockResolvedValue(list([person()], { summary: { total: 1, with_alerts: 1, without_mfa: 0, admins: 0, disabled: 0, in_one_tool: 0, tools: { cipp: 1 }, alert_sources: { huntress: 2, petra: 1 } } }));
    show();
    await screen.findAllByTestId('identity-row');
    const menu = screen.getByLabelText('Alerts from');
    expect(within(menu).getAllByRole('option').map((o) => o.textContent)).toEqual(['Alerts from any tool', 'Huntress (2)', 'Petra (1)']);
    await userEvent.selectOptions(menu, 'petra');
    await waitFor(() => expect(lastQuery().alertSource).toBe('petra'));
    expect(lastQuery().page).toBe(1);
  });

  it('opens to the person\'s alerts grouped by tool, the tool with the most first', async () => {
    api.detail.mockResolvedValue({
      person: person({ sources: [] }),
      alerts: [
        { id: 'a1', title: 'Impossible travel', severity: 'high', status: 'new', source: 'petra', created_at: null },
        { id: 'a2', title: 'Risky sign-in', severity: 'medium', status: 'new', source: 'huntress', created_at: null },
        { id: 'a3', title: 'Another risky sign-in', severity: 'low', status: 'new', source: 'huntress', created_at: null },
        { id: 'a4', title: 'No tool', severity: 'info', status: 'new', source: null, created_at: null },
      ],
      signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null },
    });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const groups = await screen.findAllByTestId('alert-group');
    expect(groups.map((g) => g.textContent?.match(/Huntress|Petra|Other/)?.[0])).toEqual(['Huntress', 'Other', 'Petra']);
    expect(groups[0]).toHaveTextContent('(2)');
    expect(within(groups[0]).getAllByRole('link')).toHaveLength(2);
  });
});

describe('groupBySource', () => {
  it('groups, puts the biggest group first and files an alert with no tool under other', async () => {
    const { groupBySource } = await import('./IdentitiesView');
    const out = groupBySource([{ source: 'b' }, { source: 'a' }, { source: 'a' }, { source: null }]);
    expect(Object.keys(out)).toEqual(['a', 'b', 'other']);
    expect(out.a).toHaveLength(2);
  });
});

describe('backups on a person', () => {
  const backups = [
    { vendor: 'dropsuite', status: 'stale', detail: 'Last Dropsuite backup 9 days ago' },
    { vendor: 'datto-saas', status: 'ok', detail: 'Protected by Datto SaaS Protection (active seat)' },
  ];

  it('shows each backup tool\'s state on the row, with the reason on hover', async () => {
    api.list.mockResolvedValue(list([person({ backups })], { summary: { total: 1, with_alerts: 0, without_mfa: 0, admins: 0, disabled: 0, in_one_tool: 0, tools: {}, backup_problems: 1 } }));
    show();
    const row = await screen.findByTestId('identity-row');
    const cell = within(row).getByTestId('backups');
    expect(cell).toHaveTextContent('No recent backup');
    expect(cell).toHaveTextContent('Backed up');
    expect(within(cell).getByTitle('Last Dropsuite backup 9 days ago')).toBeInTheDocument();
  });

  it('shows a dash for a person no backup tool knows', async () => {
    api.list.mockResolvedValue(list([person({ backups: [] })]));
    show();
    expect(within(await screen.findByTestId('backups')).getByText('—')).toBeInTheDocument();
  });

  it('filters by backup state from the menu and the problems tile', async () => {
    api.list.mockResolvedValue(list([person()], { summary: { total: 1, with_alerts: 0, without_mfa: 0, admins: 0, disabled: 0, in_one_tool: 0, tools: {}, backup_problems: 4 } }));
    show();
    await screen.findAllByTestId('identity-row');
    expect(screen.getByRole('button', { name: /Backup problems/ })).toHaveTextContent('4');
    await userEvent.click(screen.getByRole('button', { name: /Backup problems/ }));
    await waitFor(() => expect(lastQuery().backup).toBe('problem'));
    await userEvent.selectOptions(screen.getByLabelText('Backup'), 'none');
    await waitFor(() => expect(lastQuery().backup).toBe('none'));
    expect(lastQuery().page).toBe(1);
  });

  it('opens to a Backups section that says what each tool reports', async () => {
    api.detail.mockResolvedValue({ person: person({ backups, sources: [] }), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const section = await screen.findByTestId('backup-detail');
    expect(section).toHaveTextContent('Last Dropsuite backup 9 days ago');
    expect(section).toHaveTextContent('Protected by Datto SaaS Protection (active seat)');
  });

  const exposure = { count: 3, latest: '2025-02-10', password: true, stealer_log: false, malware: false, breaches: [{ name: 'Acme Forum', date: '2023-05-01', data: ['Email addresses', 'Passwords'] }] };

  it('marks a person found in breaches, in red when a password or stealer log was involved, and a dash for everyone else', async () => {
    api.list.mockResolvedValue(list([person({ exposure }), person({ key: 'c1:bo@acme.com', email: 'bo@acme.com', exposure: { ...exposure, count: 1, password: false } }), person({ key: 'c1:cy@acme.com', email: 'cy@acme.com' })]));
    show();
    const cells = (await screen.findAllByTestId('exposure')).map((c) => c.textContent);
    expect(cells).toEqual(['3 · password', '1', '—']);
    expect(within(screen.getAllByTestId('exposure')[0]).getByTitle('In 3 breaches, newest 2025-02-10')).toBeInTheDocument();
  });

  it('filters by breach exposure from the two tiles', async () => {
    api.list.mockResolvedValue(list([person()], { summary: { total: 1, with_alerts: 0, without_mfa: 0, admins: 0, disabled: 0, in_one_tool: 0, tools: {}, exposed: 9, exposed_serious: 4 } }));
    show();
    await screen.findAllByTestId('identity-row');
    expect(screen.getByRole('button', { name: /Exposed in a breach/ })).toHaveTextContent('9');
    expect(screen.getByRole('button', { name: /Password or stealer log/ })).toHaveTextContent('4');
    await userEvent.click(screen.getByRole('button', { name: /Exposed in a breach/ }));
    await waitFor(() => expect(lastQuery().exposed).toBe('any'));
    await userEvent.click(screen.getByRole('button', { name: /Password or stealer log/ }));
    await waitFor(() => expect(lastQuery().exposed).toBe('serious'));
  });

  it('opens to a list of the breaches and what kinds of data leaked', async () => {
    api.detail.mockResolvedValue({ person: person({ exposure, sources: [] }), alerts: [], signins: { last_30_days: 0, failed: 0, unusual: 0, countries: [], last_at: null } });
    show();
    await userEvent.click((await screen.findAllByTestId('identity-row'))[0]);
    const section = await screen.findByTestId('exposure-detail');
    expect(section).toHaveTextContent('Found in breaches (3)');
    expect(section).toHaveTextContent('Acme Forum');
    expect(section).toHaveTextContent('Leaked: Email addresses, Passwords');
  });
});

describe('the export', () => {
  it('asks for the CSV with the filters on screen, and hands the file to the browser', async () => {
    api.exportCsv.mockResolvedValue('Client,Address');
    const create = vi.fn(() => 'blob:x');
    const revoke = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    show();
    await screen.findAllByTestId('identity-row');
    await userEvent.selectOptions(screen.getByLabelText('Multi-Factor'), 'none');
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(api.exportCsv).toHaveBeenCalledWith(expect.objectContaining({ mfa: 'none' }));
    expect(revoke).toHaveBeenCalledWith('blob:x');
    vi.unstubAllGlobals();
  });

  it('says so when the export fails', async () => {
    api.exportCsv.mockRejectedValue(new Error('Export failed (500)'));
    show();
    await screen.findAllByTestId('identity-row');
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Export failed (500)');
  });
});
