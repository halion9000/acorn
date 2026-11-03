import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

import RemoteToolsView, { categoryLabel, counts, filterTools, parseIds, reach, type Inventory, type ToolRow } from './RemoteToolsView';

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

describe('where it is installed, and whose server it connects to', () => {
  const PATH = 'C:\Program Files (x86)\ScreenConnect Client (1111222233334444)';
  const withSc = (trusted: string[], foreign: number) =>
    inventory({
      tools: [tool({ key: 'screenconnect', name: 'ScreenConnect', category: 'remote_support', verdict: 'allowed', devices: 3, has_instances: true, trusted_instances: trusted, foreign_installs: foreign })],
    });

  it('splits identifiers on commas, spaces and semicolons and lower-cases them', () => {
    expect(parseIds(' 798CEBDB8316A8FF, 1111222233334444;aaaa bbbb ')).toEqual(['798cebdb8316a8ff', '1111222233334444', 'aaaa', 'bbbb']);
    expect(parseIds('  ')).toEqual([]);
  });

  it('shows the install folder of each device and marks an install for another server', async () => {
    serve(withSc(['798cebdb8316a8ff'], 1), [
      { client_id: 'c1', client_name: 'Acme', hostname: 'PC-1', version: '24.1', last_seen: '2026-11-03T14:28:00Z', verdict: 'allowed', install_path: PATH, instance_id: '1111222233334444', foreign: true },
      { client_id: 'c1', client_name: 'Acme', hostname: 'PC-2', version: '24.1', last_seen: '2026-11-03T14:28:00Z', verdict: 'allowed', install_path: 'C:\Program Files (x86)\ScreenConnect Client (798cebdb8316a8ff)', instance_id: '798cebdb8316a8ff', foreign: false },
    ]);
    render(<RemoteToolsView />);
    expect(await screen.findByTestId('foreign-screenconnect')).toHaveTextContent('(1 for another server)');
    await userEvent.click(screen.getByRole('button', { name: 'ScreenConnect' }));
    const panel = await screen.findByTestId('devices-screenconnect');
    const paths = within(panel).getAllByTestId('install-path');
    expect(paths[0]).toHaveTextContent(PATH);
    expect(within(panel).getByRole('columnheader', { name: 'Server ID' })).toBeInTheDocument();
    const ids = within(panel).getAllByTestId('server-id');
    expect(ids[0]).toHaveTextContent('1111222233334444');
    expect(ids[0]).toHaveTextContent('(another server)');
    expect(ids[0]).toHaveClass('text-red-300');
    expect(ids[1]).toHaveTextContent('798cebdb8316a8ff');
    expect(ids[1]).not.toHaveTextContent('another server');
  });

  it('says plainly when none of your identifiers is set, and shows them once they are', async () => {
    serve(withSc([], 0));
    const first = render(<RemoteToolsView />);
    expect(await screen.findByTestId('instances-screenconnect')).toHaveTextContent('Not set: installs for another server are not being checked.');
    first.unmount();
    serve(withSc(['798cebdb8316a8ff'], 0));
    render(<RemoteToolsView />);
    expect(await screen.findByTestId('instances-screenconnect')).toHaveTextContent('Your server identifier: 798cebdb8316a8ff');
  });

  it('saves your identifiers as a clean list, says how many critical alerts that raised, and reloads', async () => {
    authFetch.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'PUT') return json({ tool_key: 'screenconnect', ids: JSON.parse(String(init.body)).ids, alerts_raised: 2 });
      return json(withSc([], 0));
    });
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set yours' }));
    await userEvent.type(screen.getByLabelText('Your ScreenConnect server identifiers'), '798CEBDB8316A8FF');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ScreenConnect server identifiers saved (798cebdb8316a8ff). 2 critical alerts raised'));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/remote-tools/tools/screenconnect/instances');
    expect(JSON.parse(put[1].body)).toEqual({ ids: ['798cebdb8316a8ff'] });
    expect(authFetch.mock.calls.filter((c) => String(c[0]).endsWith('/inventory')).length).toBe(2);
  });

  it('shows what the API says when an identifier is refused, and keeps the editor open', async () => {
    authFetch.mockImplementation((url: string, init?: { method?: string }) => (init?.method === 'PUT' ? json({ detail: 'zzz is not a server identifier (it is 8 to 40 letters a to f and digits)' }, 422) : json(withSc([], 0))));
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set yours' }));
    await userEvent.type(screen.getByLabelText('Your ScreenConnect server identifiers'), 'zzz');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('zzz is not a server identifier');
    expect(screen.getByLabelText('Your ScreenConnect server identifiers')).toBeInTheDocument();
  });

  it('offers no identifier editor for a tool that has no server identifier', async () => {
    serve();
    render(<RemoteToolsView />);
    await screen.findByTestId('tools-table');
    expect(screen.queryByTestId('instances-teamviewer')).toBeNull();
  });
});


describe('adding a tool by hand', () => {
  const mine = [{ key: 'custom_acme', name: 'Acme Remote', category: 'remote_access', match: 'Acme Remote Desk', publisher: null }];

  function serveCustom(list: unknown[] = []) {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    let current = list;
    authFetch.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
      const method = init?.method ?? 'GET';
      calls.push({ url, method, body: init?.body ? JSON.parse(init.body) : undefined });
      if (url.endsWith('/custom') && method === 'POST') {
        const b = JSON.parse(String(init!.body));
        current = [...current, { key: 'custom_new', name: b.name, category: b.category, match: b.match, publisher: b.publisher }];
        return json({ key: 'custom_new', ...b }, 201);
      }
      if (url.includes('/custom/') && method === 'DELETE') {
        current = [];
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) });
      }
      if (url.endsWith('/custom')) return json(current);
      return json(inventory());
    });
    return calls;
  }

  it('lists the tools added with what each looks for, and offers a way to remove each', async () => {
    serveCustom(mine);
    render(<RemoteToolsView />);
    const list = await screen.findByTestId('custom-list');
    expect(list).toHaveTextContent('Acme Remote');
    expect(list).toHaveTextContent('Remote access');
    expect(list).toHaveTextContent('Acme Remote Desk');
    expect(within(list).getByRole('button', { name: 'Remove Acme Remote' })).toBeInTheDocument();
  });

  it('adds a tool from the form, sends what was typed with the publisher left out when empty, says when it will be looked for, and shows it', async () => {
    const calls = serveCustom([]);
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a tool' }));
    await userEvent.type(screen.getByLabelText('Tool name'), 'Zed Remote');
    await userEvent.selectOptions(screen.getByLabelText('Tool kind'), 'remote_support');
    await userEvent.type(screen.getByLabelText('Program name contains'), 'Zed Remote Agent');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Zed Remote added. It is looked for in the next scan of your devices (within a day).'));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.body).toEqual({ name: 'Zed Remote', category: 'remote_support', match: 'Zed Remote Agent', publisher: null });
    expect(await screen.findByTestId('custom-list')).toHaveTextContent('Zed Remote');
    expect(screen.queryByLabelText('Tool name')).toBeNull(); // the form closed
  });

  it('keeps the form open and shows the reason when a tool is refused', async () => {
    authFetch.mockImplementation((url: string, init?: { method?: string }) => {
      if (url.endsWith('/custom') && init?.method === 'POST') return json({ detail: 'AnyDesk is already in the list and a program called that is found already' }, 409);
      if (url.endsWith('/custom')) return json([]);
      return json(inventory());
    });
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a tool' }));
    await userEvent.type(screen.getByLabelText('Tool name'), 'Any');
    await userEvent.type(screen.getByLabelText('Program name contains'), 'AnyDesk');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AnyDesk is already in the list');
    expect(screen.getByLabelText('Tool name')).toHaveValue('Any');
  });

  it('removes a tool only after asking, and says a 403 plainly', async () => {
    const calls = serveCustom(mine);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Remove Acme Remote' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Remove Acme Remote?'));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Remove Acme Remote' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/v1/remote-tools/custom/custom_acme')).toBe(true));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Acme Remote removed.'));
  });

  it('says plainly that adding needs permission to manage clients', async () => {
    authFetch.mockImplementation((url: string, init?: { method?: string }) => (url.endsWith('/custom') && init?.method === 'POST' ? json({ detail: 'forbidden' }, 403) : url.endsWith('/custom') ? json([]) : json(inventory())));
    render(<RemoteToolsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a tool' }));
    await userEvent.type(screen.getByLabelText('Tool name'), 'Zed');
    await userEvent.type(screen.getByLabelText('Program name contains'), 'Zed Remote');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You need permission to manage clients to add a tool.');
  });

  it('names the new kind of tool, tunnels, in plain words', () => {
    expect(categoryLabel('tunnel')).toBe('Tunnel / VPN');
  });
});
