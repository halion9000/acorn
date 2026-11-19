import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { UiShowcase } from './UiShowcase';

describe('UiShowcase', () => {
  it('shows each shared piece and lets the period control change', async () => {
    render(<UiShowcase />);
    const page = screen.getByTestId('ui-showcase');
    expect(within(page).getAllByTestId('stat-value').length).toBe(3);
    expect(within(page).getAllByTestId('bar-cell').length).toBe(3);
    expect(within(page).getByTestId('empty-state')).toBeTruthy();
    const month = within(page).getByRole('button', { name: 'Last month' });
    await userEvent.click(month);
    expect(month.getAttribute('aria-pressed')).toBe('true');
  });
});
