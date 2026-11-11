import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ users: vi.fn(), bulkAssign: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: { bulkAssign: api.bulkAssign }, tenantsApi: { users: api.users } }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import BulkAssignBar, { assignSummary, assignUndoSummary } from './BulkAssignBar';

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

describe('undoing a bulk assign', () => {
  it('words what was put back and what was left alone', () => {
    expect(assignUndoSummary({ restored: 3, changed_since: 0, too_late: 0, not_found: 0 })).toBe('Put 3 alerts back.');
    expect(assignUndoSummary({ restored: 1, changed_since: 2, too_late: 1, not_found: 1 })).toBe(
      'Put 1 alert back. 2 had been changed since and were left alone. 1 was assigned more than 10 minutes ago. 1 could not be found.',
    );
  });

  it('offers Undo after an assign, even once the ticks are cleared, and sends back exactly what the assign answered', async () => {
    const assigned_items = [{ id: 'a1', assignee_from: 'u9', assigned_at_from: '2026-11-01T09:00:00Z' }, { id: 'a2', assignee_from: null, assigned_at_from: null }];
    api.bulkAssign.mockResolvedValue({ assigned: 2, already_finished: 0, not_found: 0, assignee_id: 'u1', assignee_name: 'amy@acme.com', assigned_items });
    const undo = vi.fn().mockResolvedValue({ restored: 2, changed_since: 0, too_late: 0, not_found: 0 });
    const onDone = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <BulkAssignBar alertIds={['a1', 'a2']} onDone={onDone} onClear={() => undefined} assign={api.bulkAssign} undo={undo} />
      </SWRConfig>,
    );
    await user.selectOptions(await screen.findByLabelText('Assign to'), 'u1');
    await user.click(screen.getByRole('button', { name: 'Assign alerts' }));
    expect(await screen.findByTestId('bulk-assign-undo')).toHaveTextContent('Changed who has 2 alerts. This can be undone for 10 minutes.');
    view.rerender(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <BulkAssignBar alertIds={[]} onDone={onDone} onClear={() => undefined} assign={api.bulkAssign} undo={undo} />
      </SWRConfig>,
    );
    expect(screen.queryByTestId('bulk-assign-bar')).toBeNull();
    await user.click(within(screen.getByTestId('bulk-assign-undo')).getByRole('button', { name: 'Undo' }));
    expect(undo).toHaveBeenCalledWith({ items: assigned_items, assignee_id: 'u1' });
    await waitFor(() => expect(screen.queryByTestId('bulk-assign-undo')).toBeNull());
    expect(onDone).toHaveBeenCalledTimes(2);
  });

  it('sends assignee null when the assign was an unassign, and offers nothing from an older server or when nothing changed', async () => {
    const undo = vi.fn().mockResolvedValue({ restored: 1, changed_since: 0, too_late: 0, not_found: 0 });
    api.bulkAssign.mockResolvedValue({ assigned: 1, already_finished: 0, not_found: 0, assignee_id: null, assignee_name: null, assigned_items: [{ id: 'a1', assignee_from: 'u1', assigned_at_from: null }] });
    const user = userEvent.setup();
    const first = render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <BulkAssignBar alertIds={['a1']} onDone={() => undefined} onClear={() => undefined} assign={api.bulkAssign} undo={undo} />
      </SWRConfig>,
    );
    await user.selectOptions(await screen.findByLabelText('Assign to'), 'none');
    await user.click(screen.getByRole('button', { name: 'Assign alerts' }));
    await user.click(within(await screen.findByTestId('bulk-assign-undo')).getByRole('button', { name: 'Undo' }));
    expect(undo).toHaveBeenCalledWith({ items: [{ id: 'a1', assignee_from: 'u1', assigned_at_from: null }], assignee_id: null });
    first.unmount();
    api.bulkAssign.mockResolvedValue({ assigned: 0, already_finished: 1, not_found: 0, assignee_id: 'u1', assignee_name: 'amy@acme.com', assigned_items: [] });
    show(['a1'], { undo });
    await user.selectOptions(await screen.findByLabelText('Assign to'), 'u1');
    await user.click(screen.getByRole('button', { name: 'Assign alerts' }));
    await waitFor(() => expect(api.bulkAssign).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('bulk-assign-undo')).toBeNull();
  });
});
