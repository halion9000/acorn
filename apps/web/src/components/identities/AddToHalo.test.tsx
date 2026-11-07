import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ caps: [] as string[], haloUserRequests: vi.fn(), requestHaloUser: vi.fn() }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ capabilities: api.caps }), freshCapabilities: () => Promise.reject(new Error('down')) },
  identitiesApi: { haloUserRequests: api.haloUserRequests, requestHaloUser: api.requestHaloUser },
}));

import { AddToHalo, canOfferAddToHalo } from './AddToHalo';

const item = (over: Record<string, unknown> = {}) => ({ id: 'h1', email: 'amy@acme.com', status: 'pending', message: null, created_at: new Date().toISOString(), finished_at: null, ...over });
const renderIt = (haloCheck: string | null = 'cloud_not_in_halo') =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AddToHalo clientId="c1" email="amy@acme.com" name="Amy Adams" haloCheck={haloCheck} />
    </SWRConfig>,
  );

beforeEach(() => {
  api.caps = ['respond_identities'];
  api.haloUserRequests.mockReset().mockResolvedValue([]);
  api.requestHaloUser.mockReset().mockResolvedValue(item());
});

describe('who sees the button', () => {
  it('only someone with the permission, and only for a person the Halo check flags', () => {
    expect(canOfferAddToHalo(['respond_identities'], 'cloud_not_in_halo')).toBe(true);
    expect(canOfferAddToHalo(['respond_identities'], 'halo_inactive_cloud_enabled')).toBe(false);
    expect(canOfferAddToHalo(['respond_identities'], null)).toBe(false);
    expect(canOfferAddToHalo(['manage_users'], 'cloud_not_in_halo')).toBe(false);
    expect(canOfferAddToHalo(undefined, 'cloud_not_in_halo')).toBe(false);
  });

  it('shows nothing, and asks the server nothing, for a person already in Halo or without the permission', () => {
    const { container } = renderIt(null);
    expect(container.textContent).toBe('');
    api.caps = [];
    const second = renderIt();
    expect(second.container.textContent).toBe('');
    expect(api.haloUserRequests).not.toHaveBeenCalled();
  });
});

describe('asking', () => {
  it('asks first, then sends the person with their name, and shows that CORE is working on it', async () => {
    const user = userEvent.setup();
    renderIt();
    await user.click(await screen.findByRole('button', { name: 'Add to HaloPSA' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('amy@acme.com');
    expect(api.requestHaloUser).not.toHaveBeenCalled();
    api.haloUserRequests.mockResolvedValue([item()]);
    await user.click(screen.getByRole('button', { name: 'Yes, add to HaloPSA' }));
    await waitFor(() => expect(api.requestHaloUser).toHaveBeenCalledWith({ client_id: 'c1', email: 'amy@acme.com', name: 'Amy Adams', confirm: true }));
    expect(await screen.findByTestId('add-to-halo-status')).toHaveTextContent('Waiting for CORE');
  });

  it('says what CORE said when it failed, and shows the refusal when the request is not accepted', async () => {
    api.haloUserRequests.mockResolvedValue([item({ status: 'failed', message: 'HaloPSA refused: no site.' })]);
    renderIt();
    expect(await screen.findByTestId('add-to-halo-status')).toHaveTextContent('HaloPSA refused: no site.');
    api.requestHaloUser.mockRejectedValue(new Error('This client is not linked to a HaloPSA client'));
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Add to HaloPSA' }));
    await user.click(screen.getByRole('button', { name: 'Yes, add to HaloPSA' }));
    expect(await screen.findByText(/not linked to a HaloPSA client/)).toBeInTheDocument();
  });
});
