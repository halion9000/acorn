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
const rename = vi.hoisted(() => vi.fn());
const apiErrorDetail = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const avatarFromFile = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({
  __esModule: true,
  authApi: { currentUser: () => currentUser(), updateUserPreferences: (p: unknown) => updateUserPreferences(p) },
  tenantsApi: { details: () => details(), users: () => users(), createUser: (b: unknown) => createUser(b), rename: (n: string) => rename(n) },
  apiErrorDetail: (e: unknown) => apiErrorDetail(e),
  passkeyApi: { list: async () => ({ items: [] }) },
  totpApi: { status: async () => ({ enabled: false, recovery_codes_left: 0 }) },
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
  [currentUser, updateUserPreferences, details, users, createUser, rename, apiErrorDetail, toastSuccess, toastError, avatarFromFile].forEach((m) => m.mockReset());
  window.localStorage.clear();
  details.mockResolvedValue(tenant);
  users.mockResolvedValue([member('hal.owner')]);
  apiErrorDetail.mockReturnValue(null);
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

describe('Settings > Workspace > name and id', () => {
  const openWorkspace = async () => {
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
  };

  it('no longer shows a Plan tile, and shows the tenant id with a Copy button', async () => {
    currentUser.mockReturnValue(account);
    await openWorkspace();
    expect(await screen.findByTestId('tenant-id')).toHaveTextContent(tenant.id);
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    expect(screen.queryByText(/^plan$/i)).toBeNull();
  });

  it('lets a manager rename the workspace and reloads it', async () => {
    currentUser.mockReturnValue(account);
    rename.mockResolvedValue({ ...tenant, name: 'Live Oak IT Partners' });
    await openWorkspace();
    await userEvent.click(await screen.findByRole('button', { name: 'Rename' }));
    const box = screen.getByLabelText('Workspace name');
    await userEvent.clear(box);
    await userEvent.type(box, 'Live Oak IT Partners');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith('Live Oak IT Partners'));
    expect(toastSuccess).toHaveBeenCalledWith('Workspace renamed');
    await waitFor(() => expect(details.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("shows the server's reason when the name is refused", async () => {
    currentUser.mockReturnValue(account);
    rename.mockRejectedValue(new Error('x'));
    apiErrorDetail.mockReturnValue('Use 2 to 80 characters.');
    await openWorkspace();
    await userEvent.click(await screen.findByRole('button', { name: 'Rename' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Use 2 to 80 characters.');
  });

  it('offers no Rename to someone who cannot manage the workspace', async () => {
    currentUser.mockReturnValue({ ...account, role: 'viewer', capabilities: [] });
    await openWorkspace();
    await screen.findByTestId('tenant-id');
    expect(screen.queryByRole('button', { name: 'Rename' })).toBeNull();
  });
});

describe('Settings > Workspace > the role chips on each member', () => {
  const openWorkspace = async () => {
    currentUser.mockReturnValue(account);
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
  };
  const row = (name: string) => screen.getAllByText(name)[0].closest('li') as HTMLElement;

  it('a person whose one role is a custom role shows only that role, as the editor dropdown does', async () => {
    users.mockResolvedValue([{ ...member('chris'), role: 'custom', custom_roles: [{ id: 'r1', name: 'Default' }] }]);
    await openWorkspace();
    await screen.findAllByText('chris');
    expect(within(row('chris')).getByText('Default')).toBeInTheDocument();
    expect(within(row('chris')).queryByText('custom')).not.toBeInTheDocument();
  });

  it('an older mix of a built-in role and custom roles shows every part, and a plain built-in role shows just that role', async () => {
    users.mockResolvedValue([
      { ...member('mixed'), role: 'soc_analyst', custom_roles: [{ id: 'r1', name: 'Default' }] },
      { ...member('many'), role: 'viewer', custom_roles: [{ id: 'r1', name: 'Default' }, { id: 'r2', name: 'vCIO' }] },
      { ...member('plain'), role: 'viewer', custom_roles: [] },
    ]);
    await openWorkspace();
    await screen.findAllByText('mixed');
    expect(within(row('mixed')).getByText('soc_analyst')).toBeInTheDocument();
    expect(within(row('mixed')).getByText('Default')).toBeInTheDocument();
    expect(within(row('many')).getByText('viewer')).toBeInTheDocument();
    expect(within(row('many')).getByText('vCIO')).toBeInTheDocument();
    expect(within(row('plain')).getByText('viewer')).toBeInTheDocument();
  });
});

describe('Settings > Workspace > members show their second factor', () => {
  it('warns on a person with none and names what the others have set up', async () => {
    currentUser.mockReturnValue(account);
    users.mockResolvedValue([
      { ...member('hal.owner'), passkeys: 2, authenticator: true },
      { ...member('bare'), passkeys: 0, authenticator: false },
    ]);
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
    const badges = await screen.findAllByTestId('second-factor');
    expect(badges.map((b) => b.textContent)).toEqual(['2 passkeys + authenticator app', 'No second factor']);
  });
});

describe('Settings > Workspace > the no-second-factor filter', () => {
  it('offers a count of people with no second factor and, ticked, lists only them', async () => {
    currentUser.mockReturnValue(account);
    users.mockResolvedValue([
      { ...member('hal.owner'), passkeys: 1, authenticator: false },
      { ...member('bare.one'), passkeys: 0, authenticator: false },
      { ...member('bare.two'), passkeys: 0, authenticator: false },
    ]);
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
    const box = await screen.findByTestId('no-factor-filter');
    expect(box).toHaveTextContent('Show only the 2 people with no second factor');
    expect(screen.getAllByTestId('second-factor')).toHaveLength(3);
    await userEvent.click(within(box).getByRole('checkbox'));
    expect(screen.getAllByTestId('second-factor').map((b) => b.textContent)).toEqual(['No second factor', 'No second factor']);
  });

  it('shows no filter when everybody has one, or the server does not say', async () => {
    currentUser.mockReturnValue(account);
    users.mockResolvedValue([{ ...member('hal.owner'), passkeys: 1, authenticator: false }, member('older.server')]);
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
    await screen.findByText(/members? in this workspace/);
    expect(screen.queryByTestId('no-factor-filter')).toBeNull();
  });
});

describe('Settings > Workspace > Export members', () => {
  it('saves a CSV file of the members with their second factor', async () => {
    currentUser.mockReturnValue(account);
    users.mockResolvedValue([{ ...member('hal.owner'), passkeys: 1, authenticator: true }, { ...member('bare.one'), passkeys: 0, authenticator: false }]);
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { blobs.push(b); return 'blob:members'; }), revokeObjectURL: vi.fn() });
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    renderSettings();
    await userEvent.click(await screen.findByRole('button', { name: /^workspace/i }));
    await userEvent.click(await screen.findByRole('button', { name: 'Export members (CSV)' }));
    expect(names).toHaveLength(1);
    expect(names[0]).toMatch(/^members-\d{4}-\d{2}-\d{2}\.csv$/);
    const text = await blobs[0].text();
    expect(text).toContain('hal.owner');
    expect(text).toContain('1 passkey + authenticator app');
    expect(text).toContain('bare.one');
    expect(text).toContain('No second factor');
    click.mockRestore();
  });
});

