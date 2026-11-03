import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

import RemoteToolsView, { categoryLabel, counts, filterTools, reach, type Inventory, type ToolRow } from './RemoteToolsView';

const tool = (over: Partial<ToolRow> & { key: string; name: string }): ToolRow => ({
  category: 'remote_access', clients: 1, devices: 1, last_seen: '2026-11-03T14:28:00Z', verdict: 'unreviewed', client_rules: 0, blocked_devices: 0, allowed_devices: 0, unreviewed_devices: 1, ...over,
});

const inventory = (over: Partial<Inventory> = {}): Inventory => ({
  tools_found: 3, devices_with_tools: 3581, devices_scanned: 3678, blocked_devices: 2, last_scanned: '2026-11-03T14:00:00Z',
  tools: [
    tool({ key: 'anydesk', name: 'AnyDesk', clients: 12, devices: 18, verdict: 'blocked', blocked_devices: 2 }),
    tool({ key: 'teamviewer', name: 'TeamViewer', clients: 75, devices: 530 }),
    tool({ key: 'screenconnect', name: 'ScreenConnect', category: 'remote_support', verdict: 'allowed', allowed_devices: 3427, devices: 3427, clients: 163 }),
  ],
  ...over,
});

const json = (body: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

function serve(inv: Inventory = inventory(), devices: unknown[] = []) {
  authFetch.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PUT') return json({ tool_key: 'x', verdict: JSON.parse(String(init.body)).verdict, client_id: null, alerts_raised: 2 });
    if (url.endsWith('/devices')) return json(devices);
    return json(inv);
  });
}

beforeEach(() => {
  authFetch.mockReset();
  vi.restoreAllMocks();
});

describe('helpers', () => {
  it('says how many scanned devices carry a tool, and that none were scanned when none were', () => {
    expect(reach(3581, 3678)).toBe('3,581 of 3,678');
    expect(reach(0, 0)).toBe('0 (no devices scanned yet)');
  });
  it('names the kinds in plain words and passes an unknown one through', () => {
    expect([categoryLabel('rmm'), categoryLabel('remote_support'), categoryLabel('weird')]).toEqual(['Remote monitoring', 'Remote support', 'weird']);
  });
  it('filters by the decision for every client and counts each', () => {
    const t = inventory().tools;
    expect(filterTools(t, 'blocked').map((x) => x.key)).toEqual(['anydesk']);
    expect(filterTools(t, 'all')).toHaveLength(3);
    expect(counts(t)).toEqual({ all: 3, unreviewed: 1, allowed: 1, blocked: 1 });
  });
});

describe('RemoteToolsView', () => {
  it('shows the three headline numbers and each tool with its clients, devices and decision', async () => {
    serve();
    render(<RemoteToolsView />);
    expect(await screen.findByTestId('tools-found')).toHaveTextContent('3');
    expect(screen.getByTestId('devices-with')).toHaveTextContent('3,581 of 3,678');
    expect(screen.getByTestId('blocked-devices')).toHaveTextContent('2');
    const row = screen.getByTestId('tool-anydesk');
    expect(row).toHaveTextContent('AnyDesk');
    expect(row).toHaveTextContent('12');
    expect(row).toHaveTextContent('18');
    expect(row).toHaveTextContent('(2 blocked)');
    expect(within(row).getByText('Blocked')).toBeInTheDocument();
    expect(within(screen.getByTestId('tool-teamviewer')).getByText('Unreviewed')).toBeInTheDocument();
    expect(within(screen.getByTestId('tool-screenconnect')).getByText('Approved')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open their alerts' })).toHaveAttribute('href', '/alerts?source=aisoc-remote-tools&status=all');
  });

  it('filters the list with the tabs and counts them', async () => {
    serve();
    render(<RemoteToolsView />);
    await screen.findByTestId('tools-table');
    expect(screen.getByRole('tab', { name: 'Unreviewed (1)' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Blocked (1)' }));
    expect(screen.getByTestId('tool-anydesk')).toBeInTheDocument();
    expect(screen.queryByTestId('tool-teamviewer')).toBeNull();
  });

  it('blocking asks first, then saves for every client, says how many alerts were raised, and reloads', async () => {
    serve();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Block TeamViewer' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Block TeamViewer for every client?'));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('TeamViewer is now blocked for every client. 2 alerts raised.'));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/remote-tools/tools/teamviewer/verdict');
    expect(JSON.parse(put[1].body)).toEqual({ verdict: 'blocked', client_id: null });
    expect(authFetch.mock.calls.filter((c) => String(c[0]).endsWith('/inventory')).length).toBe(2);
  });

  it('changes nothing when the person cancels the block', async () => {
    serve();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Block TeamViewer' }));
    expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT')).toBe(false);
  });

  it('approving needs no confirmation, and the button for the decision already in force is off', async () => {
    serve();
    render(<RemoteToolsView />);
    expect(await screen.findByRole('button', { name: 'Block AnyDesk' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Approve ScreenConnect' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Approve TeamViewer' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('TeamViewer is now approved for every client.'));
  });

  it('opens a tool to list its devices and lets one client be approved or follow the general decision', async () => {
    serve(inventory(), [
      { client_id: 'c1', client_name: 'Acme', hostname: 'PC-1', version: '8.0', last_seen: '2026-11-03T14:28:00Z', verdict: 'blocked' },
    ]);
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'AnyDesk' }));
    const panel = await screen.findByTestId('devices-anydesk');
    expect(within(panel).getByRole('link', { name: 'PC-1' })).toHaveAttribute('href', '/devices?search=PC-1');
    expect(panel).toHaveTextContent('Acme');
    await userEvent.click(within(panel).getByRole('button', { name: 'Approve AnyDesk for Acme' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('AnyDesk is now approved for Acme.'));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(JSON.parse(put[1].body)).toEqual({ verdict: 'allowed', client_id: 'c1' });
  });

  it('says plainly when nothing has been scanned yet, and when a scan found nothing', async () => {
    serve(inventory({ tools: [], tools_found: 0, devices_with_tools: 0, devices_scanned: 0, last_scanned: null, blocked_devices: 0 }));
    const first = render(<RemoteToolsView />);
    expect(await screen.findByTestId('empty')).toHaveTextContent('Nothing has been scanned yet');
    first.unmount();
    serve(inventory({ tools: [], tools_found: 0, devices_with_tools: 0, devices_scanned: 80, blocked_devices: 0 }));
    render(<RemoteToolsView />);
    expect(await screen.findByTestId('empty')).toHaveTextContent('No remote tools were found on the devices scanned.');
  });

  it('shows what the API says when a decision is refused, and a permission message for 403', async () => {
    authFetch.mockImplementation((url: string, init?: { method?: string }) => (init?.method === 'PUT' ? json({ detail: 'nope' }, 403) : json(inventory())));
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Approve TeamViewer' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You need permission to manage clients to decide this.');
  });

  it('shows a load failure instead of an empty page', async () => {
    authFetch.mockImplementation(() => json({}, 500));
    render(<RemoteToolsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The API answered 500');
  });
});
