/**
 * Settings > Workspace has an "Add a member" button (for people who may manage users), and Settings > Profile has a photo: upload, change, remove. The "planned for v1.1" note is gone.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';
import type { AuthUser, TenantDetails, TenantUser } from '@/lib/api';

const currentUser = vi.hoisted(() => vi.fn());
const updateUserPreferences = vi.hoisted(() => vi.fn());
const details = vi.hoisted(() => vi.fn());
const users = vi.hoisted(() => vi.fn());
const createUser = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const avatarFromFile = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({
  __esModule: true,
  authApi: { currentUser: () => currentUser(), updateUserPreferences: (p: unknown) => updateUserPreferences(p) },
  tenantsApi: { details: () => details(), users: () => users(), createUser: (b: unknown) => createUser(b) },
  apiErrorDetail: () => null,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
    }
  },
}));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: { success: toastSuccess, error: toastError } }));
vi.mock('@/lib/avatar', async (original) => ({ ...(await original<typeof import('@/lib/avatar')>()), avatarFromFile: (f: File) => avatarFromFile(f) }));

import { AvatarError } from '@/lib/avatar';
import { SettingsView } from './SettingsView';

const PICTURE = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ==';
const account: AuthUser = { id: 'u1', account_name: 'hal.owner', email: 'owner@liveoak.test', username: 'hal', role: 'tenant_admin', tenant_id: 't1', preferences: {}, capabilities: ['manage_users'] };
const tenant: TenantDetails = { id: '0b6f2a52-1c1e-4a8e-9a55-0c4a3f1d9d11', name: 'Live Oak IT', slug: 'live-oak-it', plan: 'open-source', is_active: true, created_at: '2026-10-07T12:00:00Z' };
const member = (account_name: string): TenantUser => ({ id: account_name, account_name, username: null, email: null, role: 'soc_analyst', is_active: true, last_login: null, created_at: '2026-10-07T12:00:00Z' });

function renderSettings() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SettingsView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  [currentUser, updateUserPreferences, details, users, createUser, toastSuccess, toastError, avatarFromFile].forEach((m) => m.mockReset());
  window.localStorage.clear();
  details.mockResolvedValue(tenant);
  users.mockResolvedValue([member('hal.owner')]);
});

const picture = () => new File([new Uint8Array([1, 2, 3])], 'me.png', { type: 'image/png' });

describe('Settings > Profile photo', () => {
  it('offers to upload a photo and no longer says custom avatars are planned', async () => {
    currentUser.mockReturnValue(account);
    const { container } = renderSettings();
    expect(await screen.findByRole('button', { name: 'Upload photo' })).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Planned for v1\.1|Custom avatars/);
    expect(screen.queryByRole('button', { name: 'Remove photo' })).toBeNull();
  });

  it('saves a chosen photo to the account at once and shows it', async () => {
    currentUser.mockReturnValue(account);
    avatarFromFile.mockResolvedValue(PICTURE);
    updateUserPreferences.mockResolvedValue({ ...account, preferences: { avatar: PICTURE } });
    const { container } = renderSettings();
    await screen.findByRole('button', { name: 'Upload photo' });
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, picture());
    await waitFor(() => expect(updateUserPreferences).toHaveBeenCalledWith({ avatar: PICTURE }));
    expect(toastSuccess).toHaveBeenCalledWith('Photo updated');
    expect(await screen.findByTestId('profile-avatar')).toHaveAttribute('src', PICTURE);
    expect(screen.getByRole('button', { name: 'Change photo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove photo' })).toBeInTheDocument();
  });

  it('shows a saved photo, and Remove photo clears it on the account', async () => {
    currentUser.mockReturnValue({ ...account, preferences: { avatar: PICTURE } });
    updateUserPreferences.mockResolvedValue({ ...account, preferences: {} });
    renderSettings();
    expect(await screen.findByTestId('profile-avatar')).toHaveAttribute('src', PICTURE);
    await userEvent.click(screen.getByRole('button', { name: 'Remove photo' }));
    await waitFor(() => expect(updateUserPreferences).toHaveBeenCalledWith({ avatar: null }));
    expect(toastSuccess).toHaveBeenCalledWith('Photo removed');
    await waitFor(() => expect(screen.queryByTestId('profile-avatar')).toBeNull());
  });

  it('ignores a saved "picture" that is not one (a link, say) and shows the initials instead', async () => {
    currentUser.mockReturnValue({ ...account, preferences: { avatar: 'https://evil.example/pixel.png' } });
    renderSettings();
    await screen.findByRole('button', { name: 'Upload photo' });
    expect(screen.queryByTestId('profile-avatar')).toBeNull();
  });

  it('says what is wrong with a file that cannot be used, and saves nothing', async () => {
    currentUser.mockReturnValue(account);
    avatarFromFile.mockRejectedValue(new AvatarError('Choose a PNG, JPEG, WebP or GIF picture.'));
    const { container } = renderSettings();
    await screen.findByRole('button', { name: 'Upload photo' });
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, picture(), { applyAccept: false });
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PNG, JPEG, WebP or GIF picture.');
    expect(updateUserPreferences).not.toHaveBeenCalled();
  });

  it('says so when the server could not save the photo', async () => {
    currentUser.mockReturnValue(account);
    avatarFromFile.mockResolvedValue(PICTURE);
    updateUserPreferences.mockRejectedValue(new Error('nope'));
    const { container } = renderSettings();
    await screen.findByRole('button', { name: 'Upload photo' });
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, picture());
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save your photo');
  });

  it('Save changes sends only the profile fields, so it can never overwrite the photo', async () => {
    currentUser.mockReturnValue({ ...account, preferences: { avatar: PICTURE } });
    updateUserPreferences.mockResolvedValue({ ...account, preferences: { avatar: PICTURE, profile: { displayName: 'Hal M', title: '', timezone: 'UTC' } } });
    renderSettings();
    const box = await screen.findByLabelText(/^Display name/);
    await userEvent.clear(box);
    await userEvent.type(box, 'Hal M');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUserPreferences).toHaveBeenCalled());
    expect(Object.keys(updateUserPreferences.mock.calls[0][0] as object)).toEqual(['profile']);
  });
});

describe('Settings > Workspace > Add a member', () => {
  const openWorkspace = async () => {
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
  };

  it('is offered to a person who may manage users', async () => {
    currentUser.mockReturnValue(account);
    await openWorkspace();
    expect(await screen.findByRole('button', { name: 'Add a member' })).toBeInTheDocument();
  });

  it('is not offered to anyone else', async () => {
    currentUser.mockReturnValue({ ...account, role: 'viewer', capabilities: [] });
    await openWorkspace();
    await screen.findByText('Members');
    expect(screen.queryByRole('button', { name: 'Add a member' })).toBeNull();
  });

  it('opens the form, adds the person, and refreshes the member list', async () => {
    currentUser.mockReturnValue(account);
    createUser.mockResolvedValue({ ...member('jane.doe'), username: 'Jane Doe' });
    await openWorkspace();
    await userEvent.click(await screen.findByRole('button', { name: 'Add a member' }));
    const form = screen.getByRole('form', { name: 'Add a member' });
    await userEvent.type(within(form).getByLabelText(/^Account name/), 'jane.doe');
    await userEvent.click(within(form).getByRole('button', { name: 'Generate' }));
    await userEvent.click(within(form).getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(createUser).toHaveBeenCalledTimes(1));
    expect(createUser.mock.calls[0][0]).toMatchObject({ account_name: 'jane.doe', role: 'soc_analyst' });
    expect(await screen.findByTestId('member-added')).toBeInTheDocument();
    await waitFor(() => expect(users.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole('button', { name: 'Add a member' })).toBeNull(); // hidden while the form (or its result) is open
  });
});
