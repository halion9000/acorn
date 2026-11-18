import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ ruleSuggestions: vi.fn(), hideType: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: api }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import { RuleSuggestions, suggestionText } from './RuleSuggestions';

const row = (over: Record<string, unknown> = {}) => ({ client_id: 'c1', client_name: 'Acme Dental', title: 'Disk space low', source: 'ninjaone', false_positives: 6, other_finished: 0, open_now: 1, sample_alert_id: 'a1', ...over });

beforeEach(() => {
  api.ruleSuggestions.mockReset();
  api.hideType.mockReset();
  api.ruleSuggestions.mockResolvedValue([row()]);
  api.hideType.mockResolvedValue({ hidden_alerts: 1 });
});

describe('suggestionText', () => {
  it('says how many were closed as false positives, how many another way and how many are open', () => {
    expect(suggestionText({ false_positives: 6, other_finished: 0, open_now: 1 })).toBe('6 closed as false positive, none closed any other way, 1 open now');
    expect(suggestionText({ false_positives: 9, other_finished: 1, open_now: 0 })).toBe('9 closed as false positive, 1 closed another way');
  });
});

describe('RuleSuggestions', () => {
  it('lists a proposal, asks before hiding and then hides the type for that client with no end date', async () => {
    render(<RuleSuggestions />);
    expect(await screen.findByText('Disk space low')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Hide Disk space low for Acme Dental' }));
    expect(api.hideType).not.toHaveBeenCalled();
    api.ruleSuggestions.mockResolvedValue([]);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, hide' }));
    await waitFor(() => expect(api.hideType).toHaveBeenCalledWith({ alertId: 'a1', scope: 'client', days: null }));
    await waitFor(() => expect(screen.queryByTestId('rule-suggestions')).toBeNull());
  });

  it('can be cancelled, and shows nothing when there are no proposals or the read fails', async () => {
    const { unmount } = render(<RuleSuggestions />);
    await userEvent.click(await screen.findByRole('button', { name: 'Hide Disk space low for Acme Dental' }));
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }));
    expect(screen.getByRole('button', { name: 'Hide Disk space low for Acme Dental' })).toBeTruthy();
    expect(api.hideType).not.toHaveBeenCalled();
    unmount();
    api.ruleSuggestions.mockRejectedValue(new Error('no'));
    const second = render(<RuleSuggestions />);
    await waitFor(() => expect(api.ruleSuggestions).toHaveBeenCalledTimes(2));
    expect(second.container.querySelector('[data-testid="rule-suggestions"]')).toBeNull();
  });
});
