import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ users: vi.fn(), bulkAssign: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: { bulkAssign: api.bulkAssign }, tenantsApi: { users: api.users } }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import BulkAssignBar, { assignSummary } from './BulkAssignBar';

const show = (ids = ['a1', 'a2'], extra: Partial<React.ComponentProps<typeof BulkAssignBar>> = {}) => {
  const onDone = vi.fn();
  const onClear = vi.fn();
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <BulkAssignBar alertIds={ids} onDone={onDone} onClear={onClear} assign={api.bulkAssign} {...extra} />
    </SWRConfig>,
  );
  return { onDone, onClear };
};

beforeEach(() => {
  api.users.mockReset().mockResolvedValue([
    { id: 'u1', email: 'amy@acme.com', account_name: 'amy', is_active: true },
    { id: 'u2', email: 'off@acme.com', account_name: 'off', is_active: false },
  ]);
  api.bulkAssign.mockReset().mockResolvedValue({ assigned: 2, already_finished: 0, not_found: 0, assignee_id: 'u1', assignee_name: 'amy@acme.com' });
});

describe('BulkAssignBar', () => {
  it('offers only people who are switched on, and nobody to unassign', async () => {
    show();
    expect(await screen.findByRole('option', { name: 'amy@acme.com' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'off@acme.com' })).toBeNull();
    expect(screen.getByRole('option', { name: 'Nobody (unassign)' })).toBeInTheDocument();
  });
  it('shows nothing when no alert is ticked or when people cannot be listed', async () => {
    const { container } = render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <BulkAssignBar alertIds={[]} onDone={() => {}} onClear={() => {}} assign={api.bulkAssign} />
      </SWRConfig>,
    );
    expect(container.textContent).toBe('');
    api.users.mockResolvedValue(null);
    const second = render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <BulkAssignBar alertIds={['a']} onDone={() => {}} onClear={() => {}} assign={api.bulkAssign} />
      </SWRConfig>,
    );
    await waitFor(() => expect(api.users).toHaveBeenCalled());
    expect(second.container.textContent).toBe('');
  });
  it('sends the ticked alerts to the chosen person with the note, then refreshes and clears the ticks', async () => {
    const { onDone, onClear } = show();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText('Assign to'), 'u1');
    await user.type(screen.getByLabelText('Note'), 'on call');
    await user.click(screen.getByRole('button', { name: 'Assign alerts' }));
    await waitFor(() => expect(api.bulkAssign).toHaveBeenCalledWith({ alert_ids: ['a1', 'a2'], assignee_id: 'u1', note: 'on call' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onClear).toHaveBeenCalled();
  });
  it('unassigns with no assignee, and does nothing until a choice is made', async () => {
    show();
    const user = userEvent.setup();
    expect(await screen.findByRole('button', { name: 'Assign alerts' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Assign to'), 'none');
    await user.click(screen.getByRole('button', { name: 'Assign alerts' }));
    await waitFor(() => expect(api.bulkAssign).toHaveBeenCalledWith({ alert_ids: ['a1', 'a2'], assignee_id: null }));
  });
  it('says in words what happened', () => {
    expect(assignSummary({ assigned: 3, already_finished: 1, not_found: 0, assignee_id: 'u', assignee_name: 'amy@acme.com' })).toBe('Assigned 3 alerts to amy@acme.com. 1 was already finished.');
    expect(assignSummary({ assigned: 1, already_finished: 0, not_found: 2, assignee_id: null, assignee_name: null })).toBe('Unassigned 1 alert. 2 could not be found.');
  });
});
