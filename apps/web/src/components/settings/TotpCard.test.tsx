import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ status: vi.fn(), enrol: vi.fn(), confirm: vi.fn(), disable: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), totpApi: { status: api.status, enrol: api.enrol, confirm: api.confirm, disable: api.disable } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { TotpCard } from './TotpCard';

beforeEach(() => {
  api.status.mockReset().mockResolvedValue({ enabled: false, recovery_codes_left: 0 });
  api.enrol.mockReset();
  api.confirm.mockReset();
  api.disable.mockReset();
});

describe('TotpCard', () => {
  it('sets one up in steps: key, code, then the recovery codes shown once', async () => {
    api.enrol.mockResolvedValue({ secret: 'ABCD2345ABCD2345', otpauth_uri: 'otpauth://totp/x' });
    api.confirm.mockResolvedValue({ recovery_codes: ['aaaaa-bbbbb', 'ccccc-ddddd'], note: '' });
    const user = userEvent.setup();
    render(<TotpCard />);
    await user.click(await screen.findByRole('button', { name: 'Set up an authenticator app' }));
    expect(await screen.findByTestId('totp-secret')).toHaveTextContent('ABCD2345ABCD2345');
    const qr = await screen.findByTestId('totp-qr');
    expect(qr.querySelector('svg')).not.toBeNull();
    expect(qr).toHaveAccessibleName('QR code for the authenticator app');
    await user.type(screen.getByLabelText('Code from the app'), '123456');
    api.status.mockResolvedValue({ enabled: true, recovery_codes_left: 2 });
    await user.click(screen.getByRole('button', { name: 'Turn on' }));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith('123456'));
    expect(await screen.findByTestId('totp-recovery')).toHaveTextContent('aaaaa-bbbbb');
    await user.click(screen.getByRole('button', { name: 'I have saved them' }));
    expect(await screen.findByTestId('totp-on')).toHaveTextContent('On. 2 recovery codes left.');
  });

  it('says why when the code is wrong and stays on the step', async () => {
    api.enrol.mockResolvedValue({ secret: 'ABCD', otpauth_uri: 'otpauth://totp/x' });
    api.confirm.mockRejectedValue(new Error('That code is not right.'));
    const user = userEvent.setup();
    render(<TotpCard />);
    await user.click(await screen.findByRole('button', { name: 'Set up an authenticator app' }));
    await user.type(await screen.findByLabelText('Code from the app'), '000000');
    await user.click(screen.getByRole('button', { name: 'Turn on' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.');
    expect(screen.getByTestId('totp-setup')).toBeInTheDocument();
  });

  it('turning it off asks for the password and a code', async () => {
    api.status.mockResolvedValue({ enabled: true, recovery_codes_left: 1 });
    api.disable.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    render(<TotpCard />);
    expect(await screen.findByTestId('totp-on')).toHaveTextContent('1 recovery code left.');
    await user.click(screen.getByRole('button', { name: 'Turn off…' }));
    expect(screen.getByRole('button', { name: 'Turn off' })).toBeDisabled();
    await user.type(screen.getByLabelText('Current password'), 'pw');
    await user.type(screen.getByLabelText('Code to turn it off'), '123456');
    api.status.mockResolvedValue({ enabled: false, recovery_codes_left: 0 });
    await user.click(screen.getByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(api.disable).toHaveBeenCalledWith('pw', '123456'));
    expect(await screen.findByRole('button', { name: 'Set up an authenticator app' })).toBeInTheDocument();
  });

  it('says when the setting could not be loaded instead of showing it as off', async () => {
    api.status.mockRejectedValue(new Error('boom'));
    render(<TotpCard />);
    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
    expect(screen.queryByRole('button', { name: 'Set up an authenticator app' })).not.toBeInTheDocument();
  });
});
