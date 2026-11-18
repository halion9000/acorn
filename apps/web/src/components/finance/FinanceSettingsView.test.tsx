import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { FinanceSettingsView, parseRateLines } from './FinanceSettingsView';

const agent = (agent_id: string, name: string, over: Record<string, unknown> = {}) => ({ agent_id, name, team: 'Support', active: true, rate: '65.00', source: 'default', own_rate: null, ...over });
const overview = (over: Record<string, unknown> = {}) => ({
  default_rate: '65.00',
  teams: [{ team: 'vCIO', rate: '90.00' }],
  agents: [agent('40', 'Dan Kemp', { rate: '71.24', source: 'agent', own_rate: '71.24' }), agent('41', 'Vic Cio', { team: 'vCIO', rate: '90.00', source: 'team' }), agent('42', 'Zed Old', { active: false })],
  have_agents: true,
  ...over,
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });
const calls = () => authFetch.mock.calls.map(([u, i]) => ({ url: String(u), method: i?.method as string | undefined, body: i?.body ? JSON.parse(String(i.body)) : undefined }));

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT' && String(url).endsWith('/import')) return answer({ saved: 2, unmatched: ['Nobody Known'] });
    if (init?.method) return answer({}, 204);
    if (String(url).endsWith('/software')) return answer({ have_costs: false, latest_month: null, vendors: [], counted_items: [] });
    if (String(url).endsWith('/client-groups')) return answer({ groups: [] });
    return answer(overview());
  });
});

describe('reading pasted rates', () => {
  it('takes a name and a rate per line, with commas, tabs or semicolons, and skips headers and blank lines', () => {
    const text = ['Name, Hourly rate', 'Alex Caico, 72.24', '', '"Richard, Ben", $60.12', 'Vic Cio\t90', 'Pat Kim; 1,250.5', 'no rate here', 'Too, many'].join('\r\n');
    expect(parseRateLines(text)).toEqual([
      { name: 'Alex Caico', hourly_rate: '72.24' },
      { name: 'Richard, Ben', hourly_rate: '$60.12' },
      { name: 'Vic Cio', hourly_rate: '90' },
      { name: 'Pat Kim', hourly_rate: '1,250.5' },
    ]);
    expect(parseRateLines('')).toEqual([]);
  });
});

describe('the finance settings page', () => {
  it('shows the default, the teams and every person with the rate used and where it comes from, and can sort them', async () => {
    render(<FinanceSettingsView />);
    const table = await screen.findByTestId('agent-rates');
    const names = () => within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0]!.textContent);
    expect(names()).toEqual(['Dan Kemp', 'Vic Cio', 'Zed Old (left)']);
    expect(within(table).getByText('their own rate')).toBeInTheDocument();
    expect(within(table).getByText("their team's rate")).toBeInTheDocument();
    expect(screen.getByLabelText('Default rate ($ an hour)')).toHaveValue('65.00');
    await userEvent.click(within(table).getByRole('button', { name: /Rate used/ }));
    expect(names()).toEqual(['Vic Cio', 'Dan Kemp', 'Zed Old (left)']);
  });

  it('saves one person\'s own rate, and clears it', async () => {
    render(<FinanceSettingsView />);
    const box = await screen.findByLabelText('Rate for Vic Cio');
    const save = within(box.closest('tr')!).getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: '$88.5' } });
    await userEvent.click(save);
    await waitFor(() => expect(calls().some((c) => c.method === 'PUT' && c.url === '/api/v1/finance/labor-rates')).toBe(true));
    expect(calls().find((c) => c.method === 'PUT' && c.url === '/api/v1/finance/labor-rates')!.body).toEqual({ scope: 'agent', key: '41', hourly_rate: 88.5 });
    await userEvent.click(within(screen.getByLabelText('Rate for Dan Kemp').closest('tr')!).getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(calls().some((c) => c.method === 'DELETE' && c.url === '/api/v1/finance/labor-rates?scope=agent&key=40')).toBe(true));
  });

  it('refuses a rate that is not a number from 0 to 10,000 without sending it', async () => {
    render(<FinanceSettingsView />);
    const box = await screen.findByLabelText('Rate for Vic Cio');
    fireEvent.change(box, { target: { value: '20000' } });
    await userEvent.click(within(box.closest('tr')!).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('0 to 10,000');
    expect(calls().some((c) => c.method === 'PUT')).toBe(false);
  });

  it('imports pasted rates and says how many were saved and which names fitted no one', async () => {
    render(<FinanceSettingsView />);
    await screen.findByTestId('agent-rates');
    fireEvent.change(screen.getByLabelText('Rates to import'), { target: { value: 'Dan Kemp, 71.24\nNobody Known, 50' } });
    await userEvent.click(screen.getByRole('button', { name: 'Import 2 rates' }));
    expect(await screen.findByTestId('import-note')).toHaveTextContent('2 rates saved. Not matched to one agent, so left out: Nobody Known.');
    const put = calls().find((c) => c.url === '/api/v1/finance/labor-rates/import')!;
    expect(put.body).toEqual({ rows: [{ name: 'Dan Kemp', hourly_rate: '71.24' }, { name: 'Nobody Known', hourly_rate: '50' }] });
  });

  it('says so when the page is not for this person, and when CORE has not sent the agents yet', async () => {
    authFetch.mockImplementation((u: string) => (String(u).includes('overview') ? answer({}, 403) : answer({ have_costs: false, vendors: [], counted_items: [] })));
    const { unmount } = render(<FinanceSettingsView />);
    expect(await screen.findByText('You do not have access to the finance settings.')).toBeInTheDocument();
    unmount();
    authFetch.mockImplementation(() => answer(overview({ agents: [], have_agents: false })));
    render(<FinanceSettingsView />);
    expect(await screen.findByText(/has not sent the HaloPSA agents yet/)).toBeInTheDocument();
  });
});
