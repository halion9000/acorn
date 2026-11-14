import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ investigate: vi.fn(), getInvestigation: vi.fn(), openInvestigation: vi.fn(), reportInvestigation: vi.fn() }));
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  agentsApi: { investigate: api.investigate, getInvestigation: api.getInvestigation },
  alertsApi: { openInvestigation: api.openInvestigation, reportInvestigation: api.reportInvestigation },
}));

import { AIInvestigation } from './AlertDetailView';

const run = (over: Record<string, unknown> = {}) => ({ id: 'r1', alertId: 'a1', status: 'running', startedAt: 't', ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.openInvestigation.mockResolvedValue({ case_id: 'c1', case_created: true, ticket: 'queued', ticket_note: null });
  api.investigate.mockResolvedValue(run());
  api.getInvestigation.mockResolvedValue(run({ status: 'completed', findings: '# Findings\nIt was a spray.' }));
  api.reportInvestigation.mockResolvedValue({ case_commented: true, ticket: 'queued' });
});

describe('an AI investigation reports somewhere', () => {
  it('opens a case and asks for a ticket before it starts, and says so with a link to the case', async () => {
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    const line = await screen.findByTestId('investigation-paperwork');
    expect(line).toHaveTextContent('A case was opened. A HaloPSA ticket was requested from CORE.');
    expect(screen.getByRole('link', { name: 'Open the case' })).toHaveAttribute('href', '/cases/c1');
    expect(api.openInvestigation).toHaveBeenCalledWith('a1');
    expect(api.openInvestigation.mock.invocationCallOrder[0]).toBeLessThan(api.investigate.mock.invocationCallOrder[0]);
  });

  it('puts the finished report on the case and the ticket once, and says it did', async () => {
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    await waitFor(() => expect(api.reportInvestigation).toHaveBeenCalledWith('a1', '# Findings\nIt was a spray.', 'r1'), { timeout: 8000 });
    expect(await screen.findByText(/The report was added to the case and written on the HaloPSA ticket\./)).toBeTruthy();
    expect(api.reportInvestigation).toHaveBeenCalledTimes(1);
  });

  it('says the ticket will get the report later when CORE has not opened it yet', async () => {
    api.reportInvestigation.mockResolvedValue({ case_commented: true, ticket: 'waiting' });
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    expect(await screen.findByText(/as soon as CORE has opened it/, undefined, { timeout: 8000 })).toBeTruthy();
  });

  it('still runs, and says there was nowhere to report, when the case and ticket could not be made', async () => {
    api.openInvestigation.mockRejectedValue(new Error('no'));
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    expect(await screen.findByTestId('investigation-paperwork')).toHaveTextContent('could not be opened for this run; the investigation still runs');
    expect(api.investigate).toHaveBeenCalledTimes(1);
  });

  it('a failed run reports nothing', async () => {
    api.getInvestigation.mockResolvedValue(run({ status: 'failed', error: 'boom' }));
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    expect(await screen.findByTestId('investigation-error', undefined, { timeout: 8000 })).toBeTruthy();
    expect(api.reportInvestigation).not.toHaveBeenCalled();
  });
});
