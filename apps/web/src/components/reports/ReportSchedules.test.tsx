import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), patch: vi.fn(), remove: vi.fn(), sendNow: vi.fn() }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, reportSchedulesApi: api };
});

import { ReportSchedules, whenText } from './ReportSchedules';

const sched = { id: 's1', name: 'Monday digest', report_kind: 'compliance_actions', report_label: 'Compliance action items', emails: ['amy@x.com'], frequency: 'weekly', day: 0, hour_utc: 7, enabled: true, last_run_at: '2026-11-16T07:00:12Z', last_result: 'Sent to 1.' };
const LIST = { schedules: [sched], kinds: [{ kind: 'compliance_actions', label: 'Compliance action items' }, { kind: 'open_audit_requests', label: 'Open audit requests' }] };

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue(LIST);
});
afterEach(() => cleanup());

describe('whenText', () => {
  it('says daily, weekly and monthly runs in words', () => {
    expect([whenText('daily', 0, 7), whenText('weekly', 2, 13), whenText('monthly', 5, 0)]).toEqual(['Every day at 07:00 UTC', 'Every Wednesday at 13:00 UTC', 'On day 5 of each month at 00:00 UTC']);
  });
});

describe('ReportSchedules', () => {
  it('lists each schedule with when it runs, to whom, and how it last went', async () => {
    render(<ReportSchedules />);
    const row = await screen.findByTestId('schedule');
    expect(row.textContent).toContain('Every Monday at 07:00 UTC to amy@x.com');
    expect(row.textContent).toContain('Sent to 1.');
  });

  it('schedules a report with the chosen report, addresses and time', async () => {
    api.list.mockResolvedValue({ ...LIST, schedules: [] });
    api.create.mockResolvedValue(sched);
    render(<ReportSchedules clientId="c1" />);
    await screen.findByTestId('no-schedules');
    await userEvent.type(screen.getByLabelText('Name'), 'Audit chase');
    await userEvent.selectOptions(screen.getByLabelText('Report'), 'open_audit_requests');
    await userEvent.type(screen.getByLabelText('Send to'), 'amy@x.com, bob@x.com');
    await userEvent.selectOptions(screen.getByLabelText('How often'), 'monthly');
    await userEvent.clear(screen.getByLabelText('Day of month'));
    await userEvent.type(screen.getByLabelText('Day of month'), '5');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule it' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith('c1', { name: 'Audit chase', report_kind: 'open_audit_requests', emails: ['amy@x.com', 'bob@x.com'], frequency: 'monthly', day: 5, hour_utc: 7 }));
  });

  it('sends now, switches off and deletes, and shows the server refusal', async () => {
    api.sendNow.mockResolvedValue(sched);
    api.patch.mockResolvedValue(sched);
    api.remove.mockResolvedValue(undefined);
    render(<ReportSchedules />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send Monday digest now' }));
    await waitFor(() => expect(api.sendNow).toHaveBeenCalledWith('', 's1'));
    await userEvent.click(screen.getByRole('button', { name: 'Switch off Monday digest' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('', 's1', { enabled: false }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Monday digest' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('', 's1'));
    api.sendNow.mockRejectedValue(new Error('The mail credentials are not set.'));
    await userEvent.click(screen.getByRole('button', { name: 'Send Monday digest now' }));
    expect(await screen.findByText('The mail credentials are not set.')).toBeTruthy();
  });
});
