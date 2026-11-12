import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ caps: [] as string[], fresh: null as string[] | null, accountActions: vi.fn(), requestAccountAction: vi.fn() }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ capabilities: api.caps }), freshCapabilities: () => (api.fresh ? Promise.resolve(api.fresh) : Promise.reject(new Error('down'))) },
  identitiesApi: { accountActions: api.accountActions, requestAccountAction: api.requestAccountAction },
}));

import { AccountActions, RowAccountAction, canOfferAccountActions, rowActionFor } from './AccountActions';

const item = (over: Record<string, unknown> = {}) => ({ id: 'a1', action: 'disable_user', label: 'Block sign-in', email: 'amy@acme.com', status: 'pending', message: null, requested_by: 'Hal', created_at: new Date().toISOString(), finished_at: null, ...over });
const renderIt = (knownTo = ['cipp', 'huntress']) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AccountActions clientId="c1" email="amy@acme.com" knownTo={knownTo} />
    </SWRConfig>,
  );

beforeEach(() => {
  api.caps = ['respond_identities'];
  api.fresh = null;
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

  it('shows the buttons when the server says yes even though the copy kept at sign-in predates the permission', async () => {
    api.caps = ['manage_users'];
    api.fresh = ['manage_users', 'respond_identities'];
    renderIt();
    expect(await screen.findByRole('button', { name: 'Block sign-in' })).toBeInTheDocument();
  });

  it('hides them when the server says no, even if the old copy said yes', async () => {
    api.fresh = ['manage_users'];
    const { container } = renderIt();
    await waitFor(() => expect(container.textContent).toBe(''));
  });

  it('shows nothing, and asks the server nothing, without the permission', () => {
    api.caps = [];
    const { container } = renderIt();
    expect(container.textContent).toBe('');
    expect(api.accountActions).not.toHaveBeenCalled();
  });

  it('for a person Microsoft 365 does not know it says why there are no buttons, and asks for no history', () => {
    renderIt(['huntress']);
    expect(screen.getByTestId('account-actions-unavailable')).toHaveTextContent('CIPP does not list this one');
    expect(screen.queryByRole('button')).toBeNull();
    expect(api.accountActions).not.toHaveBeenCalled();
  });
});

describe('the button on the line', () => {
  const row = (over: { knownTo?: string[]; enabled?: boolean | null } = {}) =>
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <RowAccountAction clientId="c1" email="amy@acme.com" knownTo={over.knownTo ?? ['cipp']} enabled={over.enabled === undefined ? true : over.enabled} />
      </SWRConfig>,
    );

  it('offers Block for an account that can sign in and Allow for one that is blocked', () => {
    expect(rowActionFor(true)).toBe('disable_user');
    expect(rowActionFor(null)).toBe('disable_user');
    expect(rowActionFor(false)).toBe('enable_user');
    const first = row();
    expect(screen.getByRole('button', { name: 'Block sign-in' })).toBeInTheDocument();
    first.unmount();
    row({ enabled: false });
    expect(screen.getByRole('button', { name: 'Allow sign-in' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Block sign-in' })).toBeNull();
  });

  it('shows nothing without the permission or for a person Microsoft 365 does not know', () => {
    const { container, unmount } = row({ knownTo: ['threatmate'] });
    expect(container.textContent).toBe('');
    unmount();
    api.caps = [];
    expect(row().container.textContent).toBe('');
  });

  it('asks first, sends only on Yes, then says CORE was asked instead of claiming it is done', async () => {
    row({ enabled: false });
    await userEvent.click(screen.getByRole('button', { name: 'Allow sign-in' }));
    expect(screen.getByRole('dialog', { name: 'Are you sure?' })).toHaveTextContent('lets amy@acme.com sign in');
    expect(api.requestAccountAction).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, allow sign-in' }));
    await waitFor(() => expect(api.requestAccountAction).toHaveBeenCalledWith({ client_id: 'c1', email: 'amy@acme.com', action: 'enable_user', confirm: true }));
    expect(await screen.findByRole('status')).toHaveTextContent('Allow sign-in: asked CORE');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('No sends nothing, and a refusal stays in the window', async () => {
    row();
    await userEvent.click(screen.getByRole('button', { name: 'Block sign-in' }));
    await userEvent.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(api.requestAccountAction).not.toHaveBeenCalled();
    api.requestAccountAction.mockRejectedValueOnce(new Error('This account is protected'));
    await userEvent.click(screen.getByRole('button', { name: 'Block sign-in' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, block sign-in' }));
    expect(await screen.findByText('This account is protected')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
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
