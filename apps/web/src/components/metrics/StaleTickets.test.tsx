import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StaleDetail, ageBand, groupByTech, type StaleTicket } from './StaleTickets';

const t = (id: string, agent: string, age: number, over: Partial<StaleTicket> = {}): StaleTicket => ({ ticket_id: id, client: 'Acme', agent, title: `Job ${id}`, priority: 'Low', status: 'On Hold', age_days: age, type: 'Project', opened: '2026-01-01', last_activity: '2026-11-01', idle_days: 3, ...over });
const TICKETS = [t('1', 'Dan', 45), t('2', 'Dan', 90), t('3', 'Dan', 200), t('4', 'Dan', 61), t('5', 'Julio', 31, { client: 'Birch Law', title: 'VPN down' }), t('6', '', 121)];

afterEach(() => cleanup());

describe('ageBand and groupByTech', () => {
  it('puts 30-60, 61-120 and over 120 days in their own bands at the edges', () => {
    expect([30, 60, 61, 120, 121].map(ageBand)).toEqual(['30-60', '30-60', '61-120', '61-120', '121+']);
  });

  it('groups by tech with the busiest first, counts each band, names no tech Unassigned, and filters by band, words and tech', () => {
    const all = groupByTech(TICKETS, 'any', '', '');
    expect(all.map((g) => [g.tech, g.tickets.length])).toEqual([['Dan', 4], ['Julio', 1], ['Unassigned', 1]]);
    expect(all[0]!.bands).toEqual({ '30-60': 1, '61-120': 2, '121+': 1 });
    expect(groupByTech(TICKETS, '121+', '', '').map((g) => g.tech)).toEqual(['Dan', 'Unassigned']);
    expect(groupByTech(TICKETS, 'any', 'birch vpn', '').map((g) => g.tech)).toEqual(['Julio']);
    expect(groupByTech(TICKETS, 'any', '', 'Dan').map((g) => g.tech)).toEqual(['Dan']);
  });
});

describe('the stale ticket section', () => {
  it('lists each tech with coloured counts, opens the first tech only, and shows the Rewst columns', () => {
    render(<StaleDetail tickets={TICKETS} />);
    const dan = screen.getByRole('region', { name: 'Dan' });
    expect(within(dan).getByText('1 @ 30-60')).toBeInTheDocument();
    expect(within(dan).getByText('2 @ 61-120')).toBeInTheDocument();
    expect(within(dan).getByText('1 @ 121+')).toBeInTheDocument();
    expect(within(dan).getByText('4 total')).toBeInTheDocument();
    expect(within(dan).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Ticket', 'Days Old', 'Client', 'Type', 'Summary', 'Status', 'Opened', 'Last Activity', 'Days Idle']);
    expect(within(dan).getByText('Job 3')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Julio' })).queryByText('VPN down')).toBeNull();
  });

  it('opens and closes one tech, expands all, collapses all and resets', async () => {
    render(<StaleDetail tickets={TICKETS} />);
    await userEvent.click(within(screen.getByRole('region', { name: 'Julio' })).getByRole('button'));
    expect(screen.getByText('VPN down')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }));
    expect(screen.queryByText('VPN down')).toBeNull();
    expect(screen.queryByText('Job 3')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Expand all' }));
    expect(screen.getByText('VPN down')).toBeInTheDocument();
    expect(screen.getByText('Job 3')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Search'), 'vpn');
    expect(screen.queryByRole('region', { name: 'Dan' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.getByRole('region', { name: 'Dan' })).toBeInTheDocument();
    expect((screen.getByLabelText('Search') as HTMLInputElement).value).toBe('');
  });

  it('filters by age and says so when nothing matches', async () => {
    render(<StaleDetail tickets={TICKETS} />);
    await userEvent.selectOptions(screen.getByLabelText('Age'), '121+');
    expect(screen.queryByRole('region', { name: 'Julio' })).toBeNull();
    await userEvent.type(screen.getByLabelText('Search'), 'zzzz');
    expect(screen.getByText('No stale tickets match.')).toBeInTheDocument();
  });
});
