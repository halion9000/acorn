import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ change: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), passwordApi: { change: api.change } }));

import { ChangePasswordCard } from './ChangePasswordCard';

beforeEach(() => api.change.mockReset());

describe('ChangePasswordCard', () => {
  it('only lets you press the button when the current password is typed and the new one matches twice', async () => {
    const user = userEvent.setup();
    render(<ChangePasswordCard />);
    const button = screen.getByRole('button', { name: 'Change password' });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Current password'), 'old');
    await user.type(screen.getByLabelText('New password'), 'Brand-new-pass-1');
    await user.type(screen.getByLabelText('New password again'), 'Brand-new-pass-2');
    expect(screen.getByTestId('password-mismatch')).toBeInTheDocument();
    expect(button).toBeDisabled();
    await user.clear(screen.getByLabelText('New password again'));
    await user.type(screen.getByLabelText('New password again'), 'Brand-new-pass-1');
    expect(button).toBeEnabled();
  });

  it('sends both passwords, then says every session ended and offers to sign in again', async () => {
    api.change.mockResolvedValue({ changed: true, detail: 'Password changed. Every session was ended: sign in again with the new password.' });
    const user = userEvent.setup();
    render(<ChangePasswordCard />);
    await user.type(screen.getByLabelText('Current password'), 'old');
    await user.type(screen.getByLabelText('New password'), 'Brand-new-pass-1');
    await user.type(screen.getByLabelText('New password again'), 'Brand-new-pass-1');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    await waitFor(() => expect(api.change).toHaveBeenCalledWith('old', 'Brand-new-pass-1'));
    expect(await screen.findByTestId('password-done')).toHaveTextContent('Every session was ended');
    expect(screen.getByRole('link', { name: 'Sign in again' })).toHaveAttribute('href', '/login');
  });
});
