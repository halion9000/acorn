import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { LaborHoursPanel, OpenTicketsPanel, priorityColor } from './TicketPages';

afterEach(() => cleanup());

describe('the Ticket Summary extras', () => {
  it('colors the known priorities and gives any other name one steady color', () => {
    expect(priorityColor('Critical')).toBe('#ef5350');
    expect(priorityColor(' high ')).toBe('#ffa726');
    expect(priorityColor('Low')).toBe('#66bb6a');
    expect(priorityColor('P1 Emergency')).toBe(priorityColor('P1 Emergency'));
  });

  it('shows the hours by month as bars for the period asked', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: 'x', summary: { by_month: [{ month: '2026-10', hours: 410.5 }, { month: '2026-11', hours: 120 }] } }) });
    render(<LaborHoursPanel query="months=3" />);
    const panel = await screen.findByTestId('summary-labor-hours');
    expect(within(panel).getByText('Oct 26')).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/ticket-metrics/labor-hours?months=3');
  });

  it('shows the open tickets by priority as a doughnut with the count in the middle', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: 'x', by_status: [{ status: 'New', tickets: 3 }], by_priority: [{ priority: 'High', tickets: 3 }, { priority: 'Low', tickets: 1 }] }) });
    render(<OpenTicketsPanel clientId="" />);
    const panel = await screen.findByTestId('open-priority');
    expect(within(panel).getByText('3 (75%)')).toBeInTheDocument();
    expect(within(panel).getByText('4')).toBeInTheDocument();
  });
});
