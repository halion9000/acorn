import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { FleetPosture, changeWord, clientHref, endsText, groupSelection, pointsText } from './FleetPosture';

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));

let originalFetch: (url: string) => Promise<Response>;
beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    if (url.endsWith('/fleet/boards')) return json({ renewals: { title: 'Renewals and expiries', keys: ['meraki_licence'] }, windows: { title: 'Windows support and updates', keys: [] } });
    if (url.endsWith('/fleet/summary'))
      return json({
        generated_at: '2026-10-25T00:00:00Z',
        average_score: 40,
        clients: [
          { client_id: 'c1', client_name: 'Acme', score: 40, met: 1, partly: 1, not_met: 3, accepted: 0, stale_tools: ['ninjaone'], target: 80, below_target: true },
          { client_id: 'c2', client_name: 'Beta', score: null, met: 0, partly: 0, not_met: 0, accepted: 2, stale_tools: [] },
        ],
      });
    if (url.includes('/fleet/boards/renewals')) return json({ board: 'renewals', title: 'Renewals', keys: [], rows: [{ client_id: 'c1', client_name: 'Acme', source: 'meraki', key: 'meraki_licence', status: 'not_met', evidence: 'The Meraki licence has expired', accepted: false, owner: 'Dana R', due_date: '2026-10-01', overdue: true }] });
    if (url.endsWith('/c1/score-breakdown'))
      return json({ client_id: 'c1', score: 40, lost: 60, rows: [{ source: 'ninjaone', key: 'ninjaone_antivirus', status: 'not_met', weight: 3, points_lost: 45 }, { source: 'ninjaone', key: 'ninjaone_patching', status: 'partly', weight: 1, points_lost: 7.5 }] });
    if (url.endsWith('/fleet/tools'))
      return json([{ source: 'slide', checks: 3, met: 1, partly: 0, not_met: 2, clients_with_problems: 2, percent_fine: 33 }, { source: 'ninjaone', checks: 8, met: 6, partly: 1, not_met: 1, clients_with_problems: 2, percent_fine: 81 }]);
    if (url.endsWith('/fleet/weights'))
      return json([{ key: 'ninjaone_antivirus', weight: 3 }]);
    if (url.includes('/fleet/weights/')) return json({ key: 'x', weight: 2 });
    if (url.includes('/fleet/search'))
      return json([{ client_id: 'c1', client_name: 'Acme', source: 'ninjaone', key: 'ninjaone_patching', status: 'not_met', evidence: '3 behind', matched_items: ['srv-02: 40 days'], matched_text: false, accepted: false }]);
    if (url.endsWith('/fleet/acceptances'))
      return json([
        { client_id: 'c1', client_name: 'Acme', key: 'ninjaone_patching', reason: 'Replacing in January', accepted_at: '2026-10-01T00:00:00Z', expires_at: new Date(Date.now() + 5 * 86_400_000 + 3_600_000).toISOString() },
        { client_id: 'c2', client_name: 'Beta', key: 'meraki_wan', reason: 'No firewall on site', accepted_at: '2026-10-02T00:00:00Z', expires_at: null, not_applicable: true },
      ]);
    if (url.endsWith('/fleet/coverage')) return json({ tools: [{ vendor: 'ninjaone', clients: 2 }, { vendor: 'slide', clients: 1 }], clients: [{ client_id: 'c1', client_name: 'Acme', tools: ['ninjaone', 'slide'], missing: [] }, { client_id: 'c2', client_name: 'Beta', tools: ['ninjaone'], missing: ['slide'] }] });
    if (url.includes('/fleet/changes')) return json([{ client_id: 'c1', client_name: 'Acme', key: 'ninjaone_antivirus', source: 'ninjaone', status: 'not_met', previous_status: 'met', observed_at: '2026-10-25T00:00:00Z' }]);
    return json({});
  });
  originalFetch = authFetch.getMockImplementation() as (url: string) => Promise<Response>;
});

describe('helpers', () => {
  it('opens a client on its own posture page', () => expect(clientHref('a b')).toBe('/settings/client-posture?client=a%20b'));
  it('says whether a change is new, worse, better or the same', () => {
    expect(changeWord({ status: 'met', previous_status: null })).toBe('new');
    expect(changeWord({ status: 'not_met', previous_status: 'partly' })).toBe('worse');
    expect(changeWord({ status: 'met', previous_status: 'not_met' })).toBe('better');
    expect(changeWord({ status: 'met', previous_status: 'met' })).toBe('same');
  });
});

describe('endsText', () => {
  const now = Date.parse('2026-10-25T12:00:00Z');
  it('says how long an acceptance has left', () => {
    expect([endsText(null, now), endsText('2026-10-26T01:00:00Z', now), endsText('2026-10-30T12:00:00Z', now), endsText('2026-10-25T09:00:00Z', now)]).toEqual(['no end date', 'ends in 1 day', 'ends in 5 days', 'ends today']);
  });
});

describe('accepting from a board', () => {
  it('groups the picked rows by check', () => {
    const g = groupSelection(['c1|meraki_wan', 'c2|meraki_wan', 'c3|meraki_licence']);
    expect([...g.entries()]).toEqual([['meraki_wan', ['c1', 'c2']], ['meraki_licence', ['c3']]]);
  });

  it('accepts the picked rows with one reason and one request per check, then reloads', async () => {
    const answers = ['Not in scope', '30'];
    vi.spyOn(window, 'prompt').mockImplementation(() => answers.shift() ?? null);
    authFetch.mockImplementation((url: string) => (url.endsWith('/fleet/acceptances') ? json({ accepted: 1, skipped: [] }) : originalFetch(url)));
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Renewals and expiries' }));
    expect(await screen.findByText('0 picked')).toBeInTheDocument();
    expect(screen.getByText('Accept picked')).toBeDisabled();
    await userEvent.click(await screen.findByLabelText('Pick Acme meraki_licence'));
    expect(screen.getByText('1 picked')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Accept picked'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/fleet/acceptances') && c[1]?.method === 'POST')).toBe(true));
    const call = authFetch.mock.calls.find((c) => c[1]?.method === 'POST')!;
    expect(JSON.parse(call[1].body)).toEqual({ key: 'meraki_licence', client_ids: ['c1'], reason: 'Not in scope', not_applicable: false, expires_in_days: 30 });
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => String(c[0]).includes('/fleet/boards/renewals')).length).toBe(2));
  });

  it('marks the picked rows not applicable with no end date, and says when some were skipped', async () => {
    vi.spyOn(window, 'prompt').mockImplementation(() => 'No firewall on site');
    authFetch.mockImplementation((url: string) => (url.endsWith('/fleet/acceptances') ? json({ accepted: 0, skipped: [{ client_id: 'c1', detail: 'Client not found' }] }) : originalFetch(url)));
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Renewals and expiries' }));
    await userEvent.click(await screen.findByLabelText('Pick Acme meraki_licence'));
    await userEvent.click(screen.getByText('Not applicable for picked'));
    expect(await screen.findByRole('alert')).toHaveTextContent('1 could not be done: Client not found');
    const body = JSON.parse(authFetch.mock.calls.find((c) => c[1]?.method === 'POST')![1].body);
    expect(body).toEqual({ key: 'meraki_licence', client_ids: ['c1'], reason: 'No firewall on site', not_applicable: true });
  });
});

describe('why a score is what it is', () => {
  it('formats the points a check cost', () => expect(pointsText(33.333)).toBe('-33.3 points'));

  it('lists what cost a client its points, biggest first, with the weight of a heavy check', async () => {
    render(<FleetPosture />);
    const row = await screen.findByTestId('fleet-client-c1');
    await userEvent.click(within(row).getByText('Why'));
    const list = await screen.findByTestId('why-c1');
    const items = within(list).getAllByRole('listitem').map((li) => li.textContent);
    expect(items[0]).toContain('ninjaone antivirus');
    expect(items[0]).toContain('counts 3 times');
    expect(items[0]).toContain('-45.0 points');
    expect(items[1]).toContain('-7.5 points');
    await userEvent.click(within(row).getByText('Hide'));
    expect(screen.queryByTestId('why-c1')).toBeNull();
  });
});

describe('FleetPosture tools and weights', () => {
  it('ranks the tools by how many of their checks are fine and lists the weights that are set', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Tools' }));
    const table = await screen.findByTestId('fleet-tools');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent(/slide/i);
    expect(rows[0]).toHaveTextContent('33%');
    expect(await screen.findByTestId('fleet-weights')).toHaveTextContent('ninjaone antivirus: counts 3 times');
  });

  it('sets a weight for a check key and resets one', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Tools' }));
    await screen.findByTestId('fleet-weights');
    await userEvent.type(screen.getByLabelText('Check key'), 'huntress_protection');
    await userEvent.selectOptions(screen.getByLabelText('Weight'), '4');
    await userEvent.click(screen.getByText('Set weight'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT' && String(c[0]).endsWith('/fleet/weights/huntress_protection'))).toBe(true));
    expect(JSON.parse(authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')![1].body)).toEqual({ weight: 4 });
    await userEvent.click(screen.getByText('Reset'));
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => c[1]?.method === 'PUT' && String(c[0]).endsWith('/fleet/weights/ninjaone_antivirus')).length).toBe(1));
    expect(JSON.parse(authFetch.mock.calls.filter((c) => c[1]?.method === 'PUT').at(-1)![1].body)).toEqual({ weight: 1 });
  });
});

describe('FleetPosture search', () => {
  it('asks the API only once two characters are typed and shows where each hit was found', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Search' }));
    await userEvent.type(screen.getByLabelText('Search the checks'), 'S{Enter}');
    expect(await screen.findByText('Type at least two characters.')).toBeInTheDocument();
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/fleet/search'))).toBe(false);
    await userEvent.type(screen.getByLabelText('Search the checks'), 'RV-02{Enter}');
    const table = await screen.findByTestId('fleet-search');
    expect(within(table).getByText('Acme')).toBeInTheDocument();
    expect(within(table).getByText(/ninjaone patching: srv-02: 40 days/)).toBeInTheDocument();
    expect(authFetch.mock.calls.some((c) => String(c[0]) === '/api/v1/client-posture/fleet/search?q=SRV-02')).toBe(true);
  });
});

describe('FleetPosture average', () => {
  it('says the fleet average and how many clients it covers', async () => {
    render(<FleetPosture />);
    expect(await screen.findByTestId('fleet-average')).toHaveTextContent('Fleet average: 40% across 1 clients with a score.');
  });
});

describe('FleetPosture targets', () => {
  it('shows a target and marks a client below it', async () => {
    render(<FleetPosture />);
    const row = await screen.findByTestId('fleet-client-c1');
    expect(row).toHaveTextContent('80% (below)');
    expect(within(screen.getByTestId('fleet-client-c2')).getByText('Set')).toBeInTheDocument();
  });

  it('sets a target from a prompt and reloads, and refuses a number outside 1 to 100 without calling the API', async () => {
    const answers = ['150', '60'];
    vi.spyOn(window, 'prompt').mockImplementation(() => answers.shift() ?? null);
    render(<FleetPosture />);
    const beta = await screen.findByTestId('fleet-client-c2');
    await userEvent.click(within(beta).getByText('Set'));
    expect(await screen.findByRole('alert')).toHaveTextContent('1 to 100');
    expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/target'))).toBe(false);
    await userEvent.click(within(screen.getByTestId('fleet-client-c2')).getByText('Set'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]) === '/api/v1/client-posture/c2/target')).toBe(true));
    const call = authFetch.mock.calls.find((c) => String(c[0]).endsWith('/target'))!;
    expect(call[1].method).toBe('PUT');
    expect(JSON.parse(call[1].body)).toEqual({ target: 60 });
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => String(c[0]).endsWith('/fleet/summary')).length).toBe(2));
  });
});

describe('FleetPosture accepted risks', () => {
  it('lists accepted risks with when they end, and marks the ones that do not apply', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Accepted risks' }));
    const table = await screen.findByTestId('fleet-accepted');
    expect(within(table).getByText('Replacing in January').closest('tr')).toHaveTextContent('ends in 6 days');
    expect(within(table).getByText('No firewall on site').closest('tr')).toHaveTextContent('not applicable');
  });
});

describe('FleetPosture coverage', () => {
  it('shows a tick where a client has the tool and a dash where it does not', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Coverage' }));
    const table = await screen.findByTestId('fleet-coverage');
    expect(within(within(table).getByTestId('coverage-c1')).getAllByText('✓')).toHaveLength(2);
    const beta = within(table).getByTestId('coverage-c2');
    expect(within(beta).getAllByText('✓')).toHaveLength(1);
    expect(within(beta).getAllByText('—')).toHaveLength(1);
  });
});

describe('FleetPosture', () => {
  it('lists clients worst first with their score, problems and the tools that stopped updating', async () => {
    render(<FleetPosture />);
    const row = await screen.findByTestId('fleet-client-c1');
    expect(within(row).getByText('40%')).toBeInTheDocument();
    expect(within(row).getByText('NinjaOne')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/settings/client-posture?client=c1');
    expect(within(screen.getByTestId('fleet-client-c2')).getByText('—')).toBeInTheDocument();
  });

  it('opens a board from its tab and shows the clients on it', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Renewals and expiries' }));
    const table = await screen.findByTestId('fleet-board-renewals');
    expect(within(table).getByText('The Meraki licence has expired')).toBeInTheDocument();
    expect(within(table).getByText('Problem')).toBeInTheDocument();
  });

  it('shows who owns a check on a board and marks an overdue one', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Renewals and expiries' }));
    expect(await screen.findByTestId('board-owner-c1-meraki_licence')).toHaveTextContent('Owner: Dana R, due 2026-10-01 (overdue)');
  });

  it('says so when a board has nothing that needs attention', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.endsWith('/fleet/boards')) return json({ windows: { title: 'Windows support and updates', keys: [] } });
      if (url.includes('/fleet/boards/windows')) return json({ board: 'windows', title: 'w', keys: [], rows: [] });
      return json({ generated_at: '', clients: [] });
    });
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Windows support and updates' }));
    expect(await screen.findByText(/board needs attention/)).toBeInTheDocument();
  });

  it('shows what changed, worse in red, and asks again for another number of days', async () => {
    render(<FleetPosture />);
    await userEvent.click(await screen.findByRole('tab', { name: 'What changed' }));
    const list = await screen.findByTestId('fleet-changes');
    expect(within(list).getByText('worse')).toBeInTheDocument();
    expect(within(list).getByText(/ninjaone antivirus is now problem/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Days'), '7');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('changes?days=7'))).toBe(true));
  });
});
