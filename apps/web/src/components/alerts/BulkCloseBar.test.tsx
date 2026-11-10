import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('react-hot-toast', () => ({ default: toast }));
vi.mock('@/lib/api', () => ({ alertsApi: { bulkClose: vi.fn(), bulkCloseUndo: vi.fn() } }));

import BulkCloseBar, { closeReason, closeSummary, undoSummary } from './BulkCloseBar';

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

describe('undoing a bulk close', () => {
  it('words what was put back and what was left alone', () => {
    expect(undoSummary({ reopened: 3, changed_since: 0, too_late: 0, not_found: 0 })).toBe('Put 3 alerts back.');
    expect(undoSummary({ reopened: 1, changed_since: 1, too_late: 2, not_found: 1 })).toBe('Put 1 alert back. 1 had been changed since and was left alone. 2 were closed more than 10 minutes ago. 1 could not be found.');
  });

  it('offers Undo after a close, even once the selection is cleared, and sends back exactly what the close answered', async () => {
    const closed_items = [{ id: 'a1', status_from: 'new' }, { id: 'a2', status_from: 'investigating' }];
    const close = vi.fn().mockResolvedValue({ closed: 2, already_finished: 0, not_found: 0, status: 'resolved', reason: 'Duplicate alerts', closed_items });
    const undo = vi.fn().mockResolvedValue({ reopened: 2, changed_since: 0, too_late: 0, not_found: 0 });
    const onDone = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<BulkCloseBar alertIds={['a1', 'a2']} onDone={onDone} onClear={() => undefined} close={close} undo={undo} />);
    expect(screen.queryByTestId('bulk-close-undo')).toBeNull();
    await user.selectOptions(screen.getByLabelText('Reason'), 'Duplicate alerts');
    await user.click(screen.getByRole('button', { name: 'Close alerts' }));
    expect(await screen.findByTestId('bulk-close-undo')).toHaveTextContent('Closed 2 alerts. This can be undone for 10 minutes.');
    rerender(<BulkCloseBar alertIds={[]} onDone={onDone} onClear={() => undefined} close={close} undo={undo} />);
    expect(screen.queryByTestId('bulk-close-bar')).toBeNull();
    await user.click(within(screen.getByTestId('bulk-close-undo')).getByRole('button', { name: 'Undo' }));
    expect(undo).toHaveBeenCalledWith({ items: closed_items, status: 'resolved' });
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Put 2 alerts back.'));
    expect(screen.queryByTestId('bulk-close-undo')).toBeNull();
    expect(onDone).toHaveBeenCalledTimes(2);
  });

  it('offers no Undo when nothing was closed or the server is an older one, and keeps the offer when the undo fails', async () => {
    const user = userEvent.setup();
    const none = vi.fn().mockResolvedValue({ closed: 0, already_finished: 2, not_found: 0, status: 'resolved', reason: 'Duplicate alerts', closed_items: [] });
    const first = render(<BulkCloseBar alertIds={['a1']} onDone={() => undefined} onClear={() => undefined} close={none} undo={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText('Reason'), 'Duplicate alerts');
    await user.click(screen.getByRole('button', { name: 'Close alerts' }));
    await waitFor(() => expect(none).toHaveBeenCalled());
    expect(screen.queryByTestId('bulk-close-undo')).toBeNull();
    first.unmount();
    const close = vi.fn().mockResolvedValue({ closed: 1, already_finished: 0, not_found: 0, status: 'resolved', reason: 'Duplicate alerts', closed_items: [{ id: 'a1', status_from: 'new' }] });
    const undo = vi.fn().mockRejectedValue(new Error('The API answered 500'));
    render(<BulkCloseBar alertIds={['a1']} onDone={() => undefined} onClear={() => undefined} close={close} undo={undo} />);
    await user.selectOptions(screen.getByLabelText('Reason'), 'Duplicate alerts');
    await user.click(screen.getByRole('button', { name: 'Close alerts' }));
    await user.click(within(await screen.findByTestId('bulk-close-undo')).getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The API answered 500'));
    expect(screen.getByTestId('bulk-close-undo')).toBeInTheDocument();
  });
});
