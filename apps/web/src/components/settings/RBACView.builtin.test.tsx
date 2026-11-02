import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig, mutate } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { RBACView } from './RBACView';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const permissions = [
  { id: 'p1', name: 'alerts:read', description: null, category: 'alerts' },
  { id: 'p2', name: 'cases:read', description: null, category: 'cases' },
  { id: 'p3', name: 'alerts:write', description: null, category: 'alerts' },
];
const builtins = [
  { key: 'viewer', label: 'Viewer', description: 'Can look, cannot change anything.', permissions: ['alerts:read', 'cases:read', 'reports:read'] },
  { key: 'tenant_admin', label: 'Administrator', description: 'Manages the workspace, its members and settings.', permissions: ['alerts:read', 'alerts:write'] },
];
let posted: { url: string; body: Record<string, unknown> } | null;

const view = () => (
  <SWRConfig value={{ dedupingInterval: 0, shouldRetryOnError: false }}>
    <RBACView />
  </SWRConfig>
);

beforeEach(async () => {
  await mutate(() => true, undefined, { revalidate: false });
  posted = null;
  authFetch.mockReset();
  authFetch.mockImplementation(async (url: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'POST') {
      posted = { url, body: JSON.parse(init.body ?? '{}') };
      return json(201, { id: 'new' });
    }
    if (url === '/api/v1/rbac/roles') return json(200, []);
    if (url === '/api/v1/rbac/permissions') return json(200, permissions);
    if (url === '/api/v1/rbac/builtin-roles') return json(200, builtins);
    return json(404, {});
  });
});
afterEach(() => vi.restoreAllMocks());

describe('the built-in roles on the Roles & Permissions page', () => {
  it('are listed, marked built-in, with what each grants one click away', async () => {
    render(view());
    const section = await screen.findByRole('region', { name: 'Built-in roles' });
    expect(within(section).getByText('Viewer')).toBeInTheDocument();
    expect(within(section).getByText('Administrator')).toBeInTheDocument();
    expect(within(section).getAllByText('built-in')).toHaveLength(2);
    await userEvent.click(within(section).getAllByRole('button', { name: /Show the 3 permissions/ })[0]);
    expect(within(section).getByText('reports:read')).toBeInTheDocument();
  });

  it('cannot be edited or deleted: only copied', async () => {
    render(view());
    const section = await screen.findByRole('region', { name: 'Built-in roles' });
    expect(within(section).queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument();
    expect(within(section).queryByRole('button', { name: /^Delete/ })).not.toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Copy Viewer to edit' })).toBeInTheDocument();
  });

  it('copying one opens the create form filled in, says what it left out, and creates a separate custom role', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'Copy Viewer to edit' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create role' });
    expect(within(dialog).getByDisplayValue('Viewer (copy)')).toBeInTheDocument();
    expect(within(dialog).getByText(/1 permission\(s\) it grants are not offered here and were left out: reports:read/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted?.url).toBe('/api/v1/rbac/roles');
    expect(posted?.body.name).toBe('Viewer (copy)');
    expect([...(posted?.body.permission_ids as string[])].sort()).toEqual(['p1', 'p2']);
  });
});
