import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { Billing, changeText, clientCsv, differenceText, disagreedAtLeast, disagreedText, gapText, sparkPoints, totalsCsv, trueUpAction, trueUpCsv } from './Billing';

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));

const mapCalls: unknown[] = [];

beforeEach(() => {
  authFetch.mockReset();
  mapCalls.length = 0;
  authFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/billing/summary'))
      return json({ generated_at: '', days: 30, rows: [{ source: 'cipp', item: 'Microsoft 365 Business Premium', unit: 'licence', clients: 12, total: 310, available: 14, change: 6 }, { source: 'ninjaone', item: 'Macs', unit: 'device', clients: 5, total: 40, available: null, change: null }] });
    if (url.startsWith('/api/v1/mssp/children')) return json([{ id: 'c2', name: 'Beta' }, { id: 'c1', name: 'Acme' }]);
    if (url.startsWith('/api/v1/billing/clients/c1/history'))
      return json({ client_id: 'c1', source: 'ninjaone', item: 'Windows workstations', days: 90, points: [{ at: '2026-08-01T00:00:00Z', count: 10 }, { at: '2026-09-01T00:00:00Z', count: 16 }, { at: '2026-10-25T00:00:00Z', count: 13 }], forecast_30d: 14 });
    if (url.startsWith('/api/v1/billing/clients/c1'))
      return json({ client_id: 'c1', days: 30, rows: [{ source: 'ninjaone', item: 'Windows workstations', unit: 'device', count: 13, available: null, change: -2, first_seen_at: '2026-09-01T00:00:00Z', updated_at: '2026-10-25T00:00:00Z' }] });
    if (url.startsWith('/api/v1/billing/reconcile'))
      return json({ generated_at: '', unmapped_lines: 2, rows: [{ client_id: 'c1', client_name: 'Acme', invoice_item: 'NinjaOne RMM (Included)', billed: 16, counted: 18, difference: 2, note_state: 'none', note: null, days: 20, since_complete: true, parts: [{ source: 'ninjaone', item: 'Macs', count: 4 }, { source: 'ninjaone', item: 'Windows workstations', count: 14 }] }, { client_id: 'c2', client_name: 'Beta', invoice_item: 'Huntress MDR', billed: 10, counted: 12, difference: 2, note_state: 'accepted', note: 'Flat package', days: 3, since_complete: true, parts: [] }, { client_id: 'c3', client_name: 'Gamma', invoice_item: 'DNS Filter', billed: 5, counted: 8, difference: 3, note_state: 'stale', note: 'Minimum of 7', days: 40, since_complete: false, parts: [] }] });
    if (url.startsWith('/api/v1/billing/map') && !mapCalls.length)
      return json({ mapped: [{ invoice_item: 'Datto SaaS (Included)', counted: [{ source: 'datto-saas', item: 'Billable seats' }] }], unmapped: [{ invoice_item: 'Huntress for Workstations (Included)', clients: 120, suggestion: [{ source: 'huntress', item: 'Agents' }], confidence: 'high' }, { invoice_item: 'NinjaOne RMM (Included)', clients: 100, suggestion: [{ source: 'ninjaone', item: 'Macs' }], confidence: 'medium' }, { invoice_item: 'Liongard (Included)', clients: 150, suggestion: [] }], counted_items: [{ source: 'liongard', item: 'Systems' }, { source: 'ninjaone', item: 'Macs' }] });
    if (url.startsWith('/api/v1/billing/map')) return json({});
    if (url.startsWith('/api/v1/billing/data-quality'))
      return json({ generated_at: '', baseline_tool: 'ninjaone', no_counts: ['blumira', 'petra'], unbilled: [{ client_id: 'c9', client_name: 'Gamma', tool: 'halopsa', tool_count: 0, baseline_count: 30, gap: -30 }, { client_id: 'c8', client_name: 'Delta', tool: 'halopsa', tool_count: 0, baseline_count: 1, gap: -1 }], rows: [{ client_id: 'c1', client_name: 'Acme', tool: 'huntress', tool_count: 30, baseline_count: 50, gap: -20 }] });
    if (url.startsWith('/api/v1/billing/last-reported'))
      return json([{ client_id: 'c2', client_name: 'Beta', source: 'dnsfilter', last_reported_at: '2026-10-19T00:00:00Z', days_ago: 6, silent: true }]);
    if (url.startsWith('/api/v1/billing/changes'))
      return json([{ client_id: 'c1', client_name: 'Acme', source: 'ninjaone', item: 'Windows workstations', unit: 'device', count: 13, previous_count: 15, observed_at: '2026-10-24T00:00:00Z' }, { client_id: 'c2', client_name: 'Beta', source: 'cipp', item: 'Business Basic', unit: 'licence', count: 5, previous_count: null, observed_at: '2026-10-23T00:00:00Z' }, { client_id: 'c1', client_name: 'Acme', source: 'ninjaone', item: 'Macs', unit: 'device', count: 3, previous_count: 10, observed_at: '2026-10-22T00:00:00Z', unusual: true }]);
    return json({});
  });
});

describe('helpers', () => {
  it('writes a change as plus, minus, no change or a dash', () => {
    expect([changeText(3), changeText(-2), changeText(0), changeText(null), changeText(undefined)]).toEqual(['+3', '-2', 'no change', '—', '—']);
  });
  it('builds a CSV with quoting for commas and quotes, and blanks where there is no number', () => {
    const csv = totalsCsv([{ source: 'cipp', item: 'Business "Premium", annual', unit: 'licence', clients: 2, total: 30, available: null, change: -1 }], 30);
    expect(csv.split('\n')[0]).toBe('Tool,Item,Unit,Clients,Total,Not assigned,Change over 30 days');
    expect(csv.split('\n')[1]).toBe('Microsoft 365 (CIPP),"Business ""Premium"", annual",licence,2,30,,-1');
    expect(clientCsv([{ source: 'ninjaone', item: 'Macs', unit: 'device', count: 4, available: null, change: null, first_seen_at: '', updated_at: '' }], 'Acme', 7).split('\n')[1]).toBe('Acme,NinjaOne,Macs,device,4,,');
  });
});

describe('gapText', () => {
  it('says which way the tool is off', () => expect([gapText(-20), gapText(5)]).toEqual(['counts 20 fewer', 'counts 5 more']));
});

describe('sparkPoints', () => {
  it('scales a series into the box: time across, higher counts higher up, and a flat series in the middle', () => {
    const pts = [{ at: '2026-10-01T00:00:00Z', count: 10 }, { at: '2026-10-03T00:00:00Z', count: 20 }, { at: '2026-10-05T00:00:00Z', count: 15 }];
    expect(sparkPoints(pts, 100, 40)).toBe('0.0,40.0 50.0,0.0 100.0,20.0');
    expect(sparkPoints([{ at: '2026-10-01T00:00:00Z', count: 5 }, { at: '2026-10-02T00:00:00Z', count: 5 }], 100, 40)).toBe('0.0,20.0 100.0,20.0');
    expect(sparkPoints([], 100, 40)).toBe('');
  });
});

describe('true-up list', () => {
  it('says what to do to a line', () => expect([trueUpAction(0), trueUpAction(2), trueUpAction(-3)]).toEqual(['no change', 'raise by 2', 'lower by 3']));
  it('lists only the lines that disagree, by client then line, with the quantity to change to and where it came from', () => {
    const row = (client: string, item: string, billed: number, counted: number) => ({ client_id: client, client_name: client, invoice_item: item, billed, counted, difference: counted - billed, parts: [{ source: 'ninjaone', item: 'Macs', count: counted }] });
    const csv = trueUpCsv([row('Beta', 'Huntress "MDR"', 10, 12), row('Acme', 'NinjaOne RMM', 16, 14), row('Acme', 'Liongard', 5, 5)]).split('\n');
    expect(csv[0]).toBe('"Client","Invoice line","Billed now","Change to","Action","Counted from"');
    expect(csv).toHaveLength(3);
    expect(csv[1]).toBe('"Acme","NinjaOne RMM","16","14","lower by 2","NinjaOne Macs: 14"');
    expect(csv[2]).toBe('"Beta","Huntress ""MDR""","10","12","raise by 2","NinjaOne Macs: 12"');
  });
});

describe('differenceText', () => {
  it('says which way it differs', () => expect([differenceText(0), differenceText(2), differenceText(-3)]).toEqual(['matches', 'uses 2 more than billed', 'billed for 3 more than used']));
});

describe('how long a line has disagreed', () => {
  it('says how many days, says so when the records start there, and says nothing for a line whose age is not known', () => {
    expect(disagreedText({ days: 20, since_complete: true })).toBe('for 20 days');
    expect(disagreedText({ days: 1, since_complete: true })).toBe('for 1 day');
    expect(disagreedText({ days: 40, since_complete: false })).toBe('for at least 40 days');
    expect(disagreedText({ days: 0, since_complete: true })).toBe('since today');
    expect(disagreedText({ days: 0, since_complete: false })).toBe('first seen today');
    expect(disagreedText({ days: null })).toBe('');
    expect(disagreedText({})).toBe('');
  });

  it('keeps only the lines that have disagreed that long, and all of them for no minimum', () => {
    const row = (days: number | null) => ({ client_id: 'c', client_name: 'C', invoice_item: 'i', billed: 1, counted: 2, difference: 1, parts: [], days });
    const rows = [row(3), row(14), row(40), row(null)];
    expect(disagreedAtLeast(rows, 0)).toHaveLength(4);
    expect(disagreedAtLeast(rows, 14).map((r) => r.days)).toEqual([14, 40]);
    expect(disagreedAtLeast(rows, 30).map((r) => r.days)).toEqual([40]);
  });
});

describe('Billing reconcile and mapping', () => {
  it('shows how long each line has disagreed and filters to the long ones', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Billed vs counted' }));
    const table = await screen.findByTestId('billing-reconcile');
    expect(within(table).getByTestId('age-c1-NinjaOne RMM (Included)')).toHaveTextContent('for 20 days');
    expect(within(table).getByTestId('age-c3-DNS Filter')).toHaveTextContent('for at least 40 days');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Disagreed for at least' }), '30');
    expect(within(screen.getByTestId('billing-reconcile')).queryByText('NinjaOne RMM (Included)')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('billing-reconcile')).getByText('DNS Filter')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Disagreed for at least' }), '0');
    expect(within(screen.getByTestId('billing-reconcile')).getByText('NinjaOne RMM (Included)')).toBeInTheDocument();
  });

  it('lists where billed and counted disagree, with the parts, and says how many lines were left out', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Billed vs counted' }));
    const table = await screen.findByTestId('billing-reconcile');
    expect(within(table).getAllByText(/uses 2 more than billed/)).toHaveLength(2);
    expect(within(table).getByText(/Macs: 4/)).toBeInTheDocument();
    expect(screen.getByText(/2 billed lines left out/)).toBeInTheDocument();
  });

  it('accepts a difference with a reason, shows an accepted one muted with its note, and flags a note that went out of date', async () => {
    vi.spyOn(window, 'prompt').mockImplementation(() => 'Minimum of 18 seats');
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Billed vs counted' }));
    const table = await screen.findByTestId('billing-reconcile');
    expect(within(table).getByText('Accepted: Flat package')).toBeInTheDocument();
    expect(screen.getByTestId('billing-accepted-count')).toHaveTextContent('1 difference(s) accepted with a reason; 2 still to look at.');
    expect(within(table).getByText(/was for a different difference/)).toBeInTheDocument();
    await userEvent.click(within(within(table).getByText('NinjaOne RMM (Included)').closest('tr')!).getByText('Accept'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT' && String(c[0]) === '/api/v1/billing/notes')).toBe(true));
    const put = authFetch.mock.calls.find((c) => String(c[0]) === '/api/v1/billing/notes')!;
    expect(JSON.parse(put[1].body)).toEqual({ client_id: 'c1', invoice_item: 'NinjaOne RMM (Included)', note: 'Minimum of 18 seats', difference: 2 });
    await userEvent.click(within(within(table).getByText('Huntress MDR').closest('tr')!).getByText('Stop accepting'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'DELETE' && String(c[0]).startsWith('/api/v1/billing/notes?client_id=c2&invoice_item=Huntress%20MDR'))).toBe(true));
  });

  it('shows what is mapped and what is still to map, and uses a suggestion on request', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Invoice mapping' }));
    expect(within(await screen.findByTestId('mapped-lines')).getByText(/Datto SaaS Protection Billable seats/)).toBeInTheDocument();
    const unmapped = screen.getByTestId('unmapped-lines');
    expect(within(unmapped).getByText('no suggestion')).toBeInTheDocument();
    mapCalls.push(1);
    await userEvent.click(within(unmapped).getAllByText('Use suggestion')[0]);
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT')).toBe(true));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/billing/map');
    expect(JSON.parse(put[1].body)).toEqual({ invoice_item: 'Huntress for Workstations (Included)', counted: [{ source: 'huntress', item: 'Agents' }] });
  });

  it('maps a line that has no suggestion by picking the tool count', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Invoice mapping' }));
    await screen.findByTestId('unmapped-lines');
    mapCalls.push(1);
    await userEvent.selectOptions(screen.getByLabelText('Map Liongard (Included) to'), 'ninjaone|Macs');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT')).toBe(true));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(JSON.parse(put[1].body)).toEqual({ invoice_item: 'Liongard (Included)', counted: [{ source: 'ninjaone', item: 'Macs' }] });
  });

  it('uses every suggestion at once, one save each, and says how many', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Invoice mapping' }));
    const button = await screen.findByText('Use all 2 suggestions');
    mapCalls.push(1);
    await userEvent.click(button);
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => c[1]?.method === 'PUT')).toHaveLength(2));
    expect(authFetch.mock.calls.filter((c) => c[1]?.method === 'PUT').map((c) => JSON.parse(c[1].body).invoice_item)).toEqual(['Huntress for Workstations (Included)', 'NinjaOne RMM (Included)']);
  });

  it('marks how sure each suggestion is and can use only the high-confidence ones', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Invoice mapping' }));
    const unmapped = await screen.findByTestId('unmapped-lines');
    expect(within(unmapped.querySelectorAll('tr')[0] as HTMLElement).getByText('high')).toBeInTheDocument();
    expect(within(unmapped.querySelectorAll('tr')[1] as HTMLElement).getByText('medium')).toBeInTheDocument();
    mapCalls.push(1);
    await userEvent.click(screen.getByText('Use the 1 high-confidence suggestions'));
    await waitFor(() => expect(authFetch.mock.calls.filter((c) => c[1]?.method === 'PUT')).toHaveLength(1));
    expect(JSON.parse(authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')![1].body).invoice_item).toBe('Huntress for Workstations (Included)');
  });

  it('removes a mapping', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Invoice mapping' }));
    const mapped = await screen.findByTestId('mapped-lines');
    mapCalls.push(1);
    await userEvent.click(within(mapped).getByText('Remove'));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(true));
    expect(authFetch.mock.calls.find((c) => c[1]?.method === 'DELETE')![0]).toBe('/api/v1/billing/map?invoice_item=Datto%20SaaS%20(Included)');
  });
});

describe('Billing', () => {
  it('shows each tool\'s total across clients with what is not assigned and the change, and a dash when the change is unknown', async () => {
    render(<Billing />);
    const table = await screen.findByTestId('billing-totals');
    const row = within(table).getByText('Microsoft 365 Business Premium').closest('tr')!;
    expect(within(row).getByText('310')).toBeInTheDocument();
    expect(within(row).getByText('+6')).toBeInTheDocument();
    const macs = within(table).getByText('Macs').closest('tr')!;
    expect(within(macs).getAllByText('—')).toHaveLength(2);
  });

  it('asks again for another comparison date', async () => {
    render(<Billing />);
    await screen.findByTestId('billing-totals');
    await userEvent.selectOptions(screen.getByLabelText('Days'), '90');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('summary?days=90'))).toBe(true));
  });

  it('shows one client\'s counts once picked', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'By client' }));
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');
    const table = await screen.findByTestId('billing-client');
    const row = within(table).getByText('Windows workstations').closest('tr')!;
    expect(within(row).getByText('13')).toBeInTheDocument();
    expect(within(row).getByText('-2')).toBeInTheDocument();
  });

  it("shows a count's trend for a client on request", async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'By client' }));
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');
    const table = await screen.findByTestId('billing-client');
    await userEvent.click(within(table).getByText('Trend'));
    const trend = await screen.findByTestId('billing-trend');
    expect(trend).toHaveTextContent('10 to 16 over 90 days; heading for about 14 in 30 days');
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/c1/history?source=ninjaone&item=Windows%20workstations'))).toBe(true);
    await userEvent.click(within(table).getByText('Hide trend'));
    expect(screen.queryByTestId('billing-trend')).toBeNull();
  });

  it('lists the changes with what a count was and is, and new items as new', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Changes' }));
    const table = await screen.findByTestId('billing-changes');
    expect(within(table).getByText('15 → 13')).toBeInTheDocument();
    expect(within(table).getByText('new: 5')).toBeInTheDocument();
    expect(within(table).getAllByText('unusual')).toHaveLength(1);
  });

  it('shows tools that count different machines than NinjaOne and tools that went silent', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Data quality' }));
    const gap = await screen.findByTestId('billing-disagree');
    expect(within(gap).getByText('counts 20 fewer')).toBeInTheDocument();
    expect(within(gap).getByText('Acme')).toBeInTheDocument();
    const silent = await screen.findByTestId('billing-silent');
    expect(within(silent).getByText('6 days ago')).toBeInTheDocument();
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('last-reported?only_silent=true'))).toBe(true);
    expect((await screen.findByTestId('billing-no-counts')).textContent).toMatch(/blumira/i);
    const unbilled = await screen.findByTestId('billing-unbilled');
    expect(unbilled).toHaveTextContent('Gamma: 30 machines');
    expect(unbilled).toHaveTextContent('Delta: 1 machine');
  });

  it('shows only what was billed when asked, as the history of invoice corrections', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Changes' }));
    await screen.findByTestId('billing-changes');
    await userEvent.selectOptions(screen.getByLabelText('Which changes'), 'halopsa');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]) === '/api/v1/billing/changes?days=30&source=halopsa')).toBe(true));
  });

  it('says so when nothing has been counted yet', async () => {
    authFetch.mockImplementation(() => json({ generated_at: '', days: 30, rows: [] }));
    render(<Billing />);
    expect(await screen.findByText(/No counts yet/)).toBeInTheDocument();
  });
});

describe('spreadsheet safety', () => {
  it('keeps text from other systems from running as a formula in either CSV, and leaves numbers alone', () => {
    const row = { client_id: 'c', client_name: '=cmd()', invoice_item: '+Huntress', billed: 1, counted: 3, difference: 2, parts: [{ source: 'huntress', item: '@Agents', count: 3 }] };
    const line = trueUpCsv([row]).split('\n')[1];
    expect(line.startsWith('"\'=cmd()","\'+Huntress","1","3"')).toBe(true);
    expect(clientCsv([{ source: 'ninjaone', item: '-Macs', unit: 'device', count: 4, available: null, change: -2, first_seen_at: '', updated_at: '' }], '=Acme', 30).split('\n')[1]).toBe("'=Acme,NinjaOne,'-Macs,device,4,,-2");
  });
});
