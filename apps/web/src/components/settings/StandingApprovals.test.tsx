import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), createMany: vi.fn(), children: vi.fn(), revoke: vi.fn(), recentApproved: vi.fn(), undo: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), msspApi: { listChildren: api.children }, standingApprovalsApi: { list: api.list, create: api.create, createForClients: api.createMany, revoke: api.revoke, recentApproved: api.recentApproved, undo: api.undo } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { StandingApprovals } from './StandingApprovals';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><StandingApprovals /></SWRConfig>);
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

beforeEach(() => {
  for (const f of [api.list, api.create, api.createMany, api.children, api.revoke, api.recentApproved, api.undo, api.toast.success, api.toast.error]) f.mockReset();
  api.list.mockResolvedValue({ allowed_types: ['add_case_comment', 'close_alert'], default_days: 90, items: [] });
  api.recentApproved.mockResolvedValue({ items: [] });
  api.children.mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }, { id: 'c2', name: 'Birch Law' }, { id: 'c3', name: 'Cedar Dental' }]);
});

describe('StandingApprovals', () => {
  it('offers only the allowed kinds, adds one for all clients for 90 days, and says so when there are none', async () => {
    api.create.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    expect(await screen.findByTestId('standing-empty')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Kind of action'), 'close_alert');
    await user.click(screen.getByRole('button', { name: 'Add standing approval' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ action_type: 'close_alert', client_id: null, days: 90 }));
  });

  it('one standing approval for each client ticked, in one request, and it says how many were already covered', async () => {
    api.createMany.mockResolvedValue({ created: [{}, {}], already_covered: ['c3'] });
    const user = userEvent.setup();
    show();
    await screen.findByTestId('standing-empty');
    await user.click(await screen.findByLabelText('Acme Dental'));
    await user.click(screen.getByLabelText('Birch Law'));
    await user.click(screen.getByLabelText('Cedar Dental'));
    await user.click(screen.getByLabelText('Birch Law')); // ticked then unticked
    await user.click(screen.getByRole('button', { name: 'Add standing approval' }));
    await waitFor(() => expect(api.createMany).toHaveBeenCalledWith({ action_type: 'add_case_comment', client_ids: ['c1', 'c3'], days: 90 }));
    expect(api.create).not.toHaveBeenCalled();
    await waitFor(() => expect(api.toast.success).toHaveBeenCalledWith('2 standing approvals added; 1 client was already covered'));
    expect(screen.getByLabelText('Acme Dental')).not.toBeChecked(); // the ticks are cleared once it is done
  });

  it('with no client list (or no clients) it offers only "all clients"', async () => {
    api.children.mockResolvedValue([]);
    show();
    expect(await screen.findByTestId('standing-clients')).toHaveTextContent('All clients');
  });

  it('lists each one with its end date and lets an active one be revoked, not an expired one', async () => {
    api.list.mockResolvedValue({
      allowed_types: ['add_case_comment'],
      default_days: 90,
      items: [
        { id: 'a1', action_type: 'add_case_comment', client_id: 'acme', note: '', created_at: iso(1), expires_at: '2027-01-01T00:00:00Z', revoked_at: null, state: 'active' },
        { id: 'a2', action_type: 'add_case_comment', client_id: null, note: '', created_at: iso(1), expires_at: '2026-01-01T00:00:00Z', revoked_at: null, state: 'expired' },
      ],
    });
    api.revoke.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    const first = await screen.findByTestId('standing-a1');
    expect(first).toHaveTextContent('client acme');
    expect(first).toHaveTextContent('until 2027-01-01');
    expect(screen.getByTestId('standing-a2')).not.toHaveTextContent('Revoke');
    await user.click(first.querySelector('button')!);
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith('a1'));
  });

  it('shows Undo only for what a standing approval approved in the last 24 hours and said how to reverse', async () => {
    api.recentApproved.mockResolvedValue({
      items: [
        { id: 'c1', title: 'Comment on case 7', status: 'approved', decided_at: iso(3_600_000), standing_approval_id: 's', undo: { how: 'delete the comment' }, undone_at: null },
        { id: 'c2', title: 'Too old', status: 'approved', decided_at: iso(30 * 3_600_000), standing_approval_id: 's', undo: { how: 'x' }, undone_at: null },
        { id: 'c3', title: 'A person approved this', status: 'approved', decided_at: iso(1000), standing_approval_id: null, undo: { how: 'x' }, undone_at: null },
        { id: 'c4', title: 'No way back', status: 'approved', decided_at: iso(1000), standing_approval_id: 's', undo: null, undone_at: null },
      ],
    });
    api.undo.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    const box = await screen.findByTestId('undo-list');
    expect(box).toHaveTextContent('Comment on case 7');
    expect(box).toHaveTextContent('undo: delete the comment');
    for (const hidden of ['Too old', 'A person approved this', 'No way back']) expect(box).not.toHaveTextContent(hidden);
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(api.undo).toHaveBeenCalledWith('c1'));
  });
});
