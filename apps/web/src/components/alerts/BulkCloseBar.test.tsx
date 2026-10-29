import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('react-hot-toast', () => ({ default: toast }));
vi.mock('@/lib/api', () => ({ alertsApi: { bulkClose: vi.fn() } }));

import BulkCloseBar, { closeReason, closeSummary } from './BulkCloseBar';

beforeEach(() => {
  toast.success.mockReset();
  toast.error.mockReset();
});

describe('closeReason', () => {
  it('is the preset, or what was typed for Other, trimmed and on one line, and empty when too short', () => {
    expect(closeReason('Duplicate alerts', '')).toBe('Duplicate alerts');
    expect(closeReason('Other', '  noisy   rule\nnow tuned ')).toBe('noisy rule now tuned');
    expect(closeReason('Other', 'no')).toBe('');
    expect(closeReason('', 'typed but no preset')).toBe('');
  });
});

describe('closeSummary', () => {
  it('says how many were closed, why, and what was left', () => {
    expect(closeSummary({ closed: 3, already_finished: 1, not_found: 2, status: 'false_positive', reason: 'Duplicate alerts' })).toBe(
      'Closed 3 alerts as false positive: Duplicate alerts. 1 was already finished. 2 could not be found.',
    );
    expect(closeSummary({ closed: 1, already_finished: 0, not_found: 0, status: 'resolved', reason: 'Expected activity' })).toBe('Closed 1 alert as resolved: Expected activity.');
  });
});

describe('BulkCloseBar', () => {
  it('shows nothing while no alert is ticked', () => {
    render(<BulkCloseBar alertIds={[]} onDone={() => undefined} onClear={() => undefined} close={vi.fn()} />);
    expect(screen.queryByTestId('bulk-close-bar')).toBeNull();
  });

  it('will not close without a reason, then closes the ticked alerts with the chosen status and reason and clears the selection', async () => {
    const close = vi.fn().mockResolvedValue({ closed: 2, already_finished: 0, not_found: 0, status: 'false_positive', reason: 'Noise from the tool' });
    const onDone = vi.fn();
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(<BulkCloseBar alertIds={['a1', 'a2']} onDone={onDone} onClear={onClear} close={close} />);
    expect(screen.getByText('Close 2 selected as')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Close alerts' });
    expect(button).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Close as'), 'false_positive');
    await user.selectOptions(screen.getByLabelText('Reason'), 'Noise from the tool');
    expect(button).toBeEnabled();
    await user.click(button);
    expect(close).toHaveBeenCalledWith({ alert_ids: ['a1', 'a2'], status: 'false_positive', reason: 'Noise from the tool' });
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Closed 2 alerts as false positive: Noise from the tool.'));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('asks for the reason in words when Other is chosen, and keeps the selection when the close fails', async () => {
    const close = vi.fn().mockRejectedValue(new Error('The API answered 500'));
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(<BulkCloseBar alertIds={['a1']} onDone={() => undefined} onClear={onClear} close={close} />);
    await user.selectOptions(screen.getByLabelText('Reason'), 'Other');
    const button = screen.getByRole('button', { name: 'Close alerts' });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Other reason'), 'rule retired');
    await user.click(button);
    expect(close).toHaveBeenCalledWith({ alert_ids: ['a1'], status: 'resolved', reason: 'rule retired' });
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The API answered 500'));
    expect(onClear).not.toHaveBeenCalled();
  });
});
