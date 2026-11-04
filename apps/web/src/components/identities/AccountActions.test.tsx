import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ caps: [] as string[], accountActions: vi.fn(), requestAccountAction: vi.fn() }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ capabilities: api.caps }) },
  identitiesApi: { accountActions: api.accountActions, requestAccountAction: api.requestAccountAction },
}));

import { AccountActions, canOfferAccountActions } from './AccountActions';

const item = (over: Record<string, unknown> = {}) => ({ id: 'a1', action: 'disable_user', label: 'Block sign-in', email: 'amy@acme.com', status: 'pending', message: null, requested_by: 'Hal', created_at: new Date().toISOString(), finished_at: null, ...over });
const renderIt = (knownTo = ['cipp', 'huntress']) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AccountActions clientId="c1" email="amy@acme.com" knownTo={knownTo} />
    </SWRConfig>,
  );

beforeEach(() => {
  api.caps = ['respond_identities'];
  api.accountActions.mockReset().mockResolvedValue({ items: [] });
  api.requestAccountAction.mockReset().mockResolvedValue(item());
});

describe('who sees the buttons', () => {
  it('only a person with the permission, and only for someone Microsoft 365 knows', () => {
    expect(canOfferAccountActions(['respond_identities'], ['cipp'])).toBe(true);
    expect(canOfferAccountActions(['manage_users'], ['cipp'])).toBe(false);
    expect(canOfferAccountActions(undefined, ['cipp'])).toBe(false);
    expect(canOfferAccountActions(['respond_identities'], ['huntress'])).toBe(false);
  });

  it('shows nothing, and asks the server nothing, without the permission', () => {
    api.caps = [];
    const { container } = renderIt();
    expect(container.textContent).toBe('');
    expect(api.accountActions).not.toHaveBeenCalled();
  });

  it('shows nothing for a person Microsoft 365 does not know', () => {
    const { container } = renderIt(['huntress']);
    expect(container.textContent).toBe('');
  });
});

describe('asking', () => {
  it('opens an Are you sure window first and sends nothing until Yes', async () => {
    renderIt();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Block sign-in' }));
    expect(screen.getByRole('dialog', { name: 'Are you sure?' })).toBeInTheDocument();
    expect(screen.getByText(/blocks amy@acme.com from signing in/)).toBeInTheDocument();
    expect(api.requestAccountAction).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.requestAccountAction).not.toHaveBeenCalled();
  });

  it('Yes sends the request with the confirmation and closes the window', async () => {
    renderIt();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));
    await user.click(screen.getByRole('button', { name: /^Yes/ }));
    await waitFor(() => expect(api.requestAccountAction).toHaveBeenCalledWith({ client_id: 'c1', email: 'amy@acme.com', action: 'revoke_sessions', confirm: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('shows the server\'s refusal in the window instead of closing it', async () => {
    api.requestAccountAction.mockRejectedValue(new Error('This client is not linked to CIPP.'));
    renderIt();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Allow sign-in' }));
    await user.click(screen.getByRole('button', { name: /^Yes/ }));
    expect(await screen.findByText('This client is not linked to CIPP.')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('what happened', () => {
  it('says Waiting, Running, Done or Failed in CORE\'s words, never Done before CORE reports it', async () => {
    api.accountActions.mockResolvedValue({
      items: [item({ id: '1', status: 'pending' }), item({ id: '2', status: 'running' }), item({ id: '3', status: 'done', message: 'Blocked' }), item({ id: '4', status: 'failed', message: 'Refused by CORE: protected account' })],
    });
    renderIt();
    const list = await screen.findByTestId('account-action-list');
    expect(list.textContent).toContain('Waiting for CORE');
    expect(list.textContent).toContain('Running');
    expect(list.textContent).toContain('Refused by CORE: protected account');
    expect(list.querySelectorAll('li').length).toBe(4);
    expect(list.textContent!.match(/Done/g)?.length).toBe(1);
  });
});
