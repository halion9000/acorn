import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ users: vi.fn(), bulkAssign: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), tenantsApi: { users: api.users }, alertsApi: { bulkAssign: api.bulkAssign } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { AssignAlert } from './AssignAlert';

const show = (onDone = vi.fn()) => render(<SWRConfig value={{ provider: () => new Map() }}><AssignAlert alertId="a1" onDone={onDone} /></SWRConfig>);

beforeEach(() => {
  for (const f of [api.users, api.bulkAssign, api.toast.success, api.toast.error]) f.mockReset();
  api.users.mockResolvedValue([
    { id: 'u1', email: 'amy@acme.com', account_name: 'amy', is_active: true },
    { id: 'u2', email: 'gone@acme.com', account_name: 'gone', is_active: false },
  ]);
});

describe('AssignAlert', () => {
  it('offers active people only and sends this one alert to the chosen person', async () => {
    api.bulkAssign.mockResolvedValue({ assigned: 1, assignee_id: 'u1', assignee_name: 'amy@acme.com', already_finished: 0, not_found: 0 });
    const onDone = vi.fn();
    const user = userEvent.setup();
    show(onDone);
    await screen.findByTestId('assign-alert');
    expect(screen.queryByRole('option', { name: 'gone@acme.com' })).toBeNull();
    const button = screen.getByRole('button', { name: 'Assign' });
    expect(button).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Assign this alert to'), 'u1');
    await user.click(button);
    await waitFor(() => expect(api.bulkAssign).toHaveBeenCalledWith({ alert_ids: ['a1'], assignee_id: 'u1' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(api.toast.success).toHaveBeenCalledWith('Assigned to amy@acme.com.');
  });
  it('can take it off whoever has it', async () => {
    api.bulkAssign.mockResolvedValue({ assigned: 1, assignee_id: null, assignee_name: null, already_finished: 0, not_found: 0 });
    const user = userEvent.setup();
    show();
    await screen.findByTestId('assign-alert');
    await user.selectOptions(screen.getByLabelText('Assign this alert to'), 'none');
    await user.click(screen.getByRole('button', { name: 'Assign' }));
    await waitFor(() => expect(api.bulkAssign).toHaveBeenCalledWith({ alert_ids: ['a1'], assignee_id: null }));
    expect(api.toast.success).toHaveBeenCalledWith('Unassigned.');
  });
  it('shows nothing to someone who cannot list people', async () => {
    api.users.mockRejectedValue(new Error('403'));
    show();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('assign-alert')).toBeNull();
  });
});
