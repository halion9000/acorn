import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { SsoDefaultRoleCard } from './SsoDefaultRoleCard';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const base = { sso_configured: true, applies_here: true, role: 'viewer', custom_role_id: null, source: 'server', allowed_builtin: ['viewer', 'soc_analyst', 'threat_hunter', 'soc_lead'] };
const roles = [{ id: 'r1', name: 'L1 Engineer' }, { id: 'r2', name: 'vCIO' }];
let current: Record<string, unknown>;
let put: Record<string, unknown> | null;
let putStatus = 200;

const card = () => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
    <SsoDefaultRoleCard customRoles={roles} />
  </SWRConfig>
);

beforeEach(() => {
  current = base;
  put = null;
  putStatus = 200;
  authFetch.mockReset();
  authFetch.mockImplementation(async (_url: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PUT') {
      put = JSON.parse(init.body ?? '{}');
      if (putStatus !== 200) return json(putStatus, { detail: 'You cannot choose a role that grants more than your own.' });
      current = { ...base, role: put!.role, custom_role_id: put!.custom_role_id, source: 'setting' };
      return json(200, current);
    }
    return json(200, current);
  });
});

describe('Role for new Microsoft sign-ins', () => {
  it('offers the built-in roles except Administrator, and the custom roles, in one dropdown', async () => {
    render(card());
    const select = await screen.findByLabelText('Role given to new people');
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Viewer', 'SOC analyst', 'Threat hunter', 'SOC lead', 'L1 Engineer', 'vCIO']);
    expect(screen.getByText(/Not chosen here yet/)).toBeInTheDocument();
    expect(screen.getByText(/Administrators are never made automatically/)).toBeInTheDocument();
  });

  it('saving a built-in role sends it, and a custom role is sent on top of Viewer', async () => {
    render(card());
    const select = await screen.findByLabelText('Role given to new people');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.selectOptions(select, 'SOC analyst');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(put).toEqual({ role: 'soc_analyst', custom_role_id: null }));
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
    expect(screen.getByText('Chosen here.')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Role given to new people'), 'vCIO');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(put).toEqual({ role: 'viewer', custom_role_id: 'r2' }));
  });

  it('shows a stored custom role as selected', async () => {
    current = { ...base, role: 'viewer', custom_role_id: 'r1', source: 'setting' };
    render(card());
    expect(await screen.findByLabelText('Role given to new people')).toHaveValue('custom:r1');
  });

  it('shows the refusal of the server as it is', async () => {
    putStatus = 403;
    render(card());
    await userEvent.selectOptions(await screen.findByLabelText('Role given to new people'), 'SOC lead');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/more than your own/);
  });

  it('is not shown when Microsoft sign-in is not set up, and says where to go when it creates people elsewhere', async () => {
    current = { ...base, sso_configured: false };
    const first = render(card());
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByLabelText('Role given to new people')).not.toBeInTheDocument();
    first.unmount();
    current = { ...base, applies_here: false };
    render(card());
    expect(await screen.findByText(/creates new people in a different workspace/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Role given to new people')).not.toBeInTheDocument();
  });
});
