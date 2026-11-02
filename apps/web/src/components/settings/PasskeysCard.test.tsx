import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const list = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());
const registerBegin = vi.hoisted(() => vi.fn());
const registerFinish = vi.hoisted(() => vi.fn());
const createPasskey = vi.hoisted(() => vi.fn());
const supported = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({
  __esModule: true,
  passkeyApi: {
    list: () => list(),
    delete: (id: string) => del(id),
    registerBegin: (n: string) => registerBegin(n),
    registerFinish: (c: string, cred: unknown) => registerFinish(c, cred),
  },
}));
vi.mock('@/lib/webauthn', () => ({ __esModule: true, createPasskey: (o: unknown) => createPasskey(o), isWebAuthnSupported: () => supported() }));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: Object.assign(vi.fn(), { success: toastSuccess, error: toastError }) }));

import { PasskeysCard } from './PasskeysCard';

const key = (id: string, name: string, last: string | null = null) => ({ id, device_name: name, created_at: '2026-10-07T12:00:00Z', last_used_at: last, transports: [] });

beforeEach(() => {
  [list, del, registerBegin, registerFinish, createPasskey, supported, toastSuccess, toastError].forEach((m) => m.mockReset());
  supported.mockReturnValue(true);
});

describe('Settings > Profile > Passkeys', () => {
  it('lists the enrolled passkeys with when they were added and last used', async () => {
    list.mockResolvedValue({ items: [key('a', 'Hal laptop', '2026-10-20T12:00:00Z'), key('b', 'Phone')] });
    render(<PasskeysCard />);
    expect(await screen.findByText('Hal laptop')).toBeInTheDocument();
    expect(screen.getByText('Phone')).toBeInTheDocument();
    expect(screen.getByText(/never used/)).toBeInTheDocument();
    expect(screen.getByText(/last used/)).toBeInTheDocument();
  });

  it('says "none yet" only when the list really is empty, and shows the error when it cannot load', async () => {
    list.mockResolvedValue({ items: [] });
    const first = render(<PasskeysCard />);
    expect(await screen.findByText(/No passkeys yet/)).toBeInTheDocument();
    first.unmount();
    list.mockRejectedValue(new Error('403 forbidden'));
    render(<PasskeysCard />);
    expect(await screen.findByRole('alert')).toHaveTextContent('403 forbidden');
    expect(screen.queryByText(/No passkeys yet/)).not.toBeInTheDocument();
  });

  it('adds a passkey: begin, ask the browser, finish with the same challenge, then reload the list', async () => {
    list.mockResolvedValueOnce({ items: [] }).mockResolvedValueOnce({ items: [key('n', 'New one')] });
    registerBegin.mockResolvedValue({ publicKey: { rp: 'x' }, challenge: 'chal-1', device_name_default: 'd' });
    createPasskey.mockResolvedValue({ id: 'cred' });
    registerFinish.mockResolvedValue(key('n', 'New one'));
    render(<PasskeysCard />);
    await screen.findByText(/No passkeys yet/);
    await userEvent.click(screen.getByRole('button', { name: 'Add a passkey' }));
    expect(await screen.findByText('New one')).toBeInTheDocument();
    expect(createPasskey).toHaveBeenCalledWith({ rp: 'x' });
    expect(registerFinish).toHaveBeenCalledWith('chal-1', { id: 'cred' });
    expect(toastSuccess).toHaveBeenCalled();
  });

  it('cancelling the browser prompt is not reported as an error', async () => {
    list.mockResolvedValue({ items: [] });
    registerBegin.mockResolvedValue({ publicKey: {}, challenge: 'c', device_name_default: 'd' });
    createPasskey.mockRejectedValue(new DOMException('no', 'NotAllowedError'));
    render(<PasskeysCard />);
    await screen.findByText(/No passkeys yet/);
    await userEvent.click(screen.getByRole('button', { name: 'Add a passkey' }));
    await waitFor(() => expect(createPasskey).toHaveBeenCalled());
    expect(toastError).not.toHaveBeenCalled();
    expect(registerFinish).not.toHaveBeenCalled();
  });

  it('revoking asks first, names the passkey, and only deletes after the person confirms', async () => {
    list.mockResolvedValueOnce({ items: [key('a', 'Hal laptop')] }).mockResolvedValueOnce({ items: [] });
    del.mockResolvedValue(undefined);
    render(<PasskeysCard />);
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke Hal laptop' }));
    expect(del).not.toHaveBeenCalled();
    expect(screen.getByText(/Hal laptop will no longer sign you in/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(del).toHaveBeenCalledWith('a'));
    expect(await screen.findByText(/No passkeys yet/)).toBeInTheDocument();
  });

  it('greys out the add button when the browser has no passkey support', async () => {
    supported.mockReturnValue(false);
    list.mockResolvedValue({ items: [] });
    render(<PasskeysCard />);
    await screen.findByText(/No passkeys yet/);
    expect(screen.getByRole('button', { name: 'Add a passkey' })).toBeDisabled();
  });
});
