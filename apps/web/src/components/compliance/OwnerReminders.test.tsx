import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ControlRowT } from '@/lib/api';
import { OwnerReminders } from './OwnerReminders';

const row = (control_id: string, state: ControlRowT['state'], owner: string | null): ControlRowT => ({ framework: 'SOC2', control_id, title: `T ${control_id}`, group: 'G', state, accepted: 0, pending: 0, rejected: 0, newest_evidence: null, age_days: null, link: '', owner });

describe('Evidence reminders by owner', () => {
  const writeText = vi.fn(() => Promise.resolve());
  beforeEach(() => {
    writeText.mockClear();
    Object.assign(navigator, { clipboard: { writeText } });
  });

  it('lists each owner with their controls and copies a message for that owner only', async () => {
    render(<OwnerReminders today="2026-11-16" rows={[row('CC1.1', 'not_tested', 'Ann'), row('CC1.2', 'healthy', 'Ann'), row('CC2.1', 'at_risk', 'Bob'), row('CC9.1', 'not_tested', null)]} />);
    expect(screen.getByText(/3 controls need evidence, 3 owners/)).toBeInTheDocument();
    expect(screen.getAllByTestId('owner-group')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: 'Copy the reminder for Ann' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = (writeText.mock.calls[0] as unknown as [string])[0];
    expect(text).toContain('Hi Ann, as of 2026-11-16, 1 control you own needs evidence:');
    expect(text).toContain('SOC2 CC1.1 T CC1.1');
    expect(text).not.toContain('CC2.1');
  });

  it('draws nothing when every control has its evidence', () => {
    const { container } = render(<OwnerReminders rows={[row('CC1.1', 'healthy', 'Ann')]} />);
    expect(container.textContent).toBe('');
  });
});
