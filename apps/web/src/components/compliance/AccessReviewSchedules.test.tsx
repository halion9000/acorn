import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ schedules: vi.fn(), saveSchedule: vi.fn(), removeSchedule: vi.fn() }));
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), accessReviewsApi: api }));

import { AccessReviewSchedules, everyText, scheduleLine } from './AccessReviewSchedules';

const row = { id: 's1', system: 'Microsoft 365', reviewer: 'hal@x', every_days: 90, next_start: '2027-02-15', enabled: true, last_review_id: null, last_error: null };

describe('Access reviews that start themselves', () => {
  beforeEach(() => {
    api.schedules.mockReset().mockResolvedValue([row]);
    api.saveSchedule.mockReset().mockResolvedValue(row);
    api.removeSchedule.mockReset().mockResolvedValue({});
  });

  it('words the interval and the line', () => {
    expect(everyText(90)).toBe('every quarter');
    expect(everyText(30)).toBe('every 30 days');
    expect(scheduleLine(row)).toBe('Microsoft 365 every quarter, next starts 2027-02-15, reviewer hal@x');
    expect(scheduleLine({ ...row, enabled: false, reviewer: null })).toBe('Microsoft 365 every quarter, switched off');
  });

  it('lists the schedules with why the last try started nothing', async () => {
    api.schedules.mockResolvedValue([{ ...row, last_error: 'There are no people to review for Microsoft 365.' }]);
    render(<AccessReviewSchedules clientId="" systems={['Microsoft 365']} />);
    expect(await screen.findByLabelText('Repeating reviews')).toHaveTextContent('every quarter');
    expect(screen.getByText(/The last try started nothing: There are no people/)).toBeInTheDocument();
  });

  it('adds a repeat, switches one off and removes one', async () => {
    const user = userEvent.setup();
    render(<AccessReviewSchedules clientId="c1" systems={['Microsoft 365']} />);
    await user.click(await screen.findByRole('button', { name: 'Switch off' }));
    await waitFor(() => expect(api.saveSchedule).toHaveBeenCalledWith('c1', { system: 'Microsoft 365', reviewer: 'hal@x', every_days: 90, enabled: false }));
    await user.click(screen.getByRole('button', { name: 'Remove the repeat for Microsoft 365' }));
    await waitFor(() => expect(api.removeSchedule).toHaveBeenCalledWith('c1', 's1'));
    await user.type(screen.getByLabelText('System to repeat'), 'Huntress');
    await user.type(screen.getByLabelText('Reviewer of the repeat'), 'amy@x');
    await user.click(screen.getByRole('button', { name: 'Repeat this review' }));
    await waitFor(() => expect(api.saveSchedule).toHaveBeenLastCalledWith('c1', { system: 'Huntress', reviewer: 'amy@x', every_days: 90, enabled: true }));
  });

  it('shows why a save was refused and renders nothing when the schedules cannot be read', async () => {
    const user = userEvent.setup();
    const { ApiError } = await import('@/lib/api');
    api.saveSchedule.mockRejectedValue(new ApiError('x', 422, JSON.stringify({ detail: 'The first start day has already passed.' })));
    render(<AccessReviewSchedules clientId="" systems={[]} />);
    await user.type(await screen.findByLabelText('System to repeat'), 'X');
    await user.click(screen.getByRole('button', { name: 'Repeat this review' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    api.schedules.mockRejectedValue(new Error('no'));
    const again = render(<AccessReviewSchedules clientId="z" systems={[]} />);
    await waitFor(() => expect(again.container.querySelector('[data-testid="review-schedules"]')).toBeNull());
  });
});
