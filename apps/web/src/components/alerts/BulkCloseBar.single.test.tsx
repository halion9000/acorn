import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import BulkCloseBar, { needsCloseReason } from './BulkCloseBar';

describe('needsCloseReason', () => {
  it('is true for the statuses that finish an alert and false for every other', () => {
    for (const s of ['resolved', 'false_positive', 'closed']) expect(needsCloseReason(s)).toBe(true);
    for (const s of ['new', 'triaging', 'in_progress', 'investigating', 'auto_closed', '']) expect(needsCloseReason(s)).toBe(false);
  });
});

describe('closing one alert from its page', () => {
  it('starts on the chosen status, will not close without a reason, and sends this one alert with that status and reason', async () => {
    const close = vi.fn().mockResolvedValue({ closed: 1, status: 'false_positive', reason: 'Noise from the tool', already_finished: 0, not_found: 0 });
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<BulkCloseBar alertIds={['a1']} defaultStatus="false_positive" onDone={onDone} onClear={() => {}} close={close} />);
    expect(screen.getByLabelText('Close as')).toHaveValue('false_positive');
    const button = screen.getByRole('button', { name: 'Close alerts' });
    expect(button).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Reason'), 'Noise from the tool');
    await user.click(button);
    await waitFor(() => expect(close).toHaveBeenCalledWith({ alert_ids: ['a1'], status: 'false_positive', reason: 'Noise from the tool' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });
});
