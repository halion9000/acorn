import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn(), approve: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), roadmapApi: api }));

import { RoadmapView, canApproveItem, datesText, replyOpen, dayText, sortedItems, tagCounts, visibleItems } from './RoadmapView';

const item = (over: Record<string, unknown> = {}) => ({
  id: 'i1', key: 'a', title: 'Vendor detected apps', detail: 'Scan the tenant', area: 'Compliance', status: 'not_started', needs: 'claude', priority: 'normal', note: '',
  completed_ref: null, created_at: '2026-11-14T10:00:00Z', updated_at: '2026-11-14T10:00:00Z', completed_at: null, ...over,
});
const roadmap = (items = [item()]) => ({
  items,
  counts: { new: items.filter((i) => i.status === 'new').length, not_started: items.filter((i) => i.status === 'not_started').length, in_progress: items.filter((i) => i.status === 'in_progress').length, completed: items.filter((i) => i.status === 'completed').length },
});
const three = [
  item(),
  item({ id: 'i2', key: 'b', title: 'Test Ninja deploy', status: 'in_progress', needs: 'hal', note: 'Press the button on SCHKNOWCROSS' }),
  item({ id: 'i3', key: 'c', title: 'Vendor register', status: 'completed', needs: 'claude', completed_ref: '4fd4d03e' }),
];

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue(roadmap(three));
  api.update.mockResolvedValue(item());
  api.add.mockResolvedValue(item());
  api.remove.mockResolvedValue(undefined);
});

describe('visibleItems', () => {
  it('filters by status and by who it waits on, both at once', () => {
    const items = three as never;
    expect(visibleItems(items, 'all', 'all')).toHaveLength(3);
    expect(visibleItems(items, 'completed', 'all').map((i) => i.title)).toEqual(['Vendor register']);
    expect(visibleItems(items, 'all', 'hal').map((i) => i.title)).toEqual(['Test Ninja deploy']);
    expect(visibleItems(items, 'in_progress', 'claude')).toEqual([]);
  });
});

describe('RoadmapView', () => {
  it('lists every item with its tag and status, and the counts on the tabs', async () => {
    render(<RoadmapView />);
    const list = await screen.findByTestId('roadmap-list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(screen.getByTestId('item-b')).getByText('Needs you to do something')).toBeTruthy();
    expect(within(screen.getByTestId('item-a')).getByText('Can do without you')).toBeTruthy();
    expect(screen.getByTestId('item-b')).toHaveTextContent('Press the button on SCHKNOWCROSS');
    expect(screen.getByRole('tab', { name: 'In progress (1)' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'All (3)' })).toBeTruthy();
  });

  it('the tabs and the waiting-on filter narrow the list', async () => {
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.click(screen.getByRole('tab', { name: 'Completed (1)' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    await userEvent.click(screen.getByRole('tab', { name: 'All (3)' }));
    await userEvent.selectOptions(screen.getByLabelText('Waiting on'), 'signoff');
    expect(screen.getByTestId('roadmap-empty')).toBeTruthy();
  });

  it('changing the priority saves it and loads the list again', async () => {
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.selectOptions(screen.getByLabelText('Priority of Vendor detected apps'), 'high');
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('i1', { priority: 'high' }));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });

  it('adds an item of its own', async () => {
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.click(screen.getByRole('button', { name: 'Add an item' }));
    await userEvent.type(screen.getByLabelText('New item title'), 'Fix the thing');
    await userEvent.click(screen.getByRole('button', { name: 'Save item' }));
    await waitFor(() => expect(api.add).toHaveBeenCalledWith({ title: 'Fix the thing', detail: '' }));
  });

  it('shows the reason when the list cannot be loaded', async () => {
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<RoadmapView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });

  it('marks an item complete, and reopens a completed one', async () => {
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.click(within(screen.getByTestId('item-b')).getByRole('button', { name: 'Mark complete' }));
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('i2', { status: 'completed' }));
    await userEvent.click(within(screen.getByTestId('item-c')).getByRole('button', { name: 'Reopen' }));
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('i3', { status: 'not_started' }));
  });

  it('removes an item only after a second click confirms it', async () => {
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.click(screen.getByRole('button', { name: 'Remove Test Ninja deploy' }));
    expect(api.remove).not.toHaveBeenCalled();
    await userEvent.click(within(screen.getByTestId('item-b')).getByRole('button', { name: 'Keep' }));
    expect(api.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove Test Ninja deploy' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, remove' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('i2'));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });
});

describe('roadmap filters and sorting', () => {
  const items = [
    item({ id: 'x1', key: 'x1', title: 'B item', area: 'Devices', created_at: '2026-11-10T00:00:00Z' }),
    item({ id: 'x2', key: 'x2', title: 'A item', area: 'Compliance', needs: 'hal', created_at: '2026-11-12T00:00:00Z' }),
    item({ id: 'x3', key: 'x3', title: 'C item', area: 'Compliance', status: 'completed', created_at: '2026-11-11T00:00:00Z' }),
  ] as never[];

  it('filters by area as well, and counts each tag and area over the items on the chosen status tab', () => {
    expect(visibleItems(items, 'all', 'all', 'Compliance').map((i: { title: string }) => i.title)).toEqual(['A item', 'C item']);
    expect(visibleItems(items, 'completed', 'all', 'Devices')).toEqual([]);
    const all = tagCounts(items, 'all');
    expect(all.needs).toEqual({ claude: 2, signoff: 0, hal: 1 });
    expect(all.areas).toEqual([['Compliance', 2], ['Devices', 1]]);
    expect(tagCounts(items, 'completed').areas).toEqual([['Compliance', 1]]);
  });

  it('sorts newest first or by area, and leaves the server order alone otherwise', () => {
    expect(sortedItems(items, 'order')).toBe(items);
    expect(sortedItems(items, 'newest').map((i: { title: string }) => i.title)).toEqual(['A item', 'C item', 'B item']);
    expect(sortedItems(items, 'area').map((i: { title: string }) => i.title)).toEqual(['A item', 'C item', 'B item']);
  });

  it('the area and sort choices narrow and reorder the list on the page', async () => {
    api.list.mockResolvedValue(roadmap([item({ id: 'a', key: 'a', title: 'Zed', area: 'Devices' }), item({ id: 'b', key: 'b', title: 'Alpha', area: 'Compliance' })]));
    render(<RoadmapView />);
    await screen.findByTestId('roadmap-list');
    await userEvent.selectOptions(screen.getByLabelText('Area'), 'Compliance');
    expect(within(screen.getByTestId('roadmap-list')).getAllByRole('listitem')).toHaveLength(1);
    await userEvent.selectOptions(screen.getByLabelText('Area'), '');
    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'area');
    const titles = within(screen.getByTestId('roadmap-list')).getAllByRole('listitem').map((li) => li.textContent ?? '');
    expect(titles[0]).toContain('Alpha');
    expect(screen.getByRole('option', { name: 'Can do without you (2)' })).toBeTruthy();
  });
});

describe('the dates under an item', () => {
  it('says when an item was added and, once it is finished, when it was completed', () => {
    expect(datesText({ created_at: '2026-11-03T12:00:00Z', completed_at: null, status: 'new' })).toBe('Added Nov 3, 2026');
    expect(datesText({ created_at: '2026-11-03T12:00:00Z', completed_at: '2026-11-16T12:00:00Z', status: 'completed' })).toBe('Added Nov 3, 2026 · Completed Nov 16, 2026');
    expect(datesText({ created_at: '2026-11-03T12:00:00Z', completed_at: '2026-11-16T12:00:00Z', status: 'in_progress' })).toBe('Added Nov 3, 2026');
    expect(datesText({ created_at: 'nonsense', completed_at: null, status: 'new' })).toBe('');
    expect(dayText(null)).toBe('');
  });

  it('shows the line on each item of the page', async () => {
    api.list.mockResolvedValue(roadmap([item({ id: 'd1', key: 'd1', title: 'Dated item', created_at: '2026-11-03T12:00:00Z' }), item({ id: 'd2', key: 'd2', title: 'Done item', status: 'completed', created_at: '2026-11-04T12:00:00Z', completed_at: '2026-11-10T12:00:00Z' })]));
    render(<RoadmapView />);
    expect(await screen.findByTestId('dates-d1')).toHaveTextContent('Added Nov 3, 2026');
    expect(screen.getByTestId('dates-d2')).toHaveTextContent('Added Nov 4, 2026 · Completed Nov 10, 2026');
  });
});

describe('approving an item that waits on sign-off', () => {
  const signoff = item({ id: 's1', key: 's1', title: 'Needs sign-off', needs: 'signoff', status: 'not_started' });
  it('offers Approve only on an open item that waits on sign-off', () => {
    expect(canApproveItem({ needs: 'signoff', status: 'new' })).toBe(true);
    expect(canApproveItem({ needs: 'signoff', status: 'completed' })).toBe(false);
    expect(canApproveItem({ needs: 'hal', status: 'new' })).toBe(false);
    expect(canApproveItem({ needs: 'claude', status: 'new' })).toBe(false);
  });

  it('shows the button next to the item, approves it and loads the list again', async () => {
    api.list.mockResolvedValue(roadmap([signoff, item({ id: 'c1', key: 'c1', title: 'Ready item' })]));
    api.approve.mockResolvedValue({ ...signoff, needs: 'claude' });
    render(<RoadmapView />);
    expect(await screen.findByRole('button', { name: 'Approve Needs sign-off' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve Ready item' })).toBeNull();
    api.list.mockResolvedValue(roadmap([item({ id: 's1', key: 's1', title: 'Needs sign-off', needs: 'claude', approved_at: '2026-11-18T12:00:00Z', approved_by: 'hal@goliveoak.com' })]));
    await userEvent.click(screen.getByRole('button', { name: 'Approve Needs sign-off' }));
    await waitFor(() => expect(api.approve).toHaveBeenCalledWith('s1'));
    expect(await screen.findByTestId('dates-s1')).toHaveTextContent('Approved by hal@goliveoak.com Nov 18, 2026');
    expect(screen.queryByRole('button', { name: 'Approve Needs sign-off' })).toBeNull();
  });
});

describe('your answer or question on an item', () => {
  it('starts open when the item waits on you or sign-off or you already wrote something, and shut otherwise', () => {
    expect(replyOpen({ needs: 'hal', status: 'new' })).toBe(true);
    expect(replyOpen({ needs: 'signoff', status: 'not_started' })).toBe(true);
    expect(replyOpen({ needs: 'claude', status: 'new', reply: 'yes' })).toBe(true);
    expect(replyOpen({ needs: 'claude', status: 'new' })).toBe(false);
    expect(replyOpen({ needs: 'hal', status: 'completed' })).toBe(false);
  });

  it('saves what is written, only when it changed, and shows who wrote it and when', async () => {
    api.list.mockResolvedValue(roadmap([item({ id: 'q1', key: 'q1', title: 'Ask me', needs: 'hal', note: 'Which vendor?', reply: '', reply_at: null })]));
    api.update.mockResolvedValue(item());
    render(<RoadmapView />);
    const box = await screen.findByLabelText('Your answer or question for Ask me');
    const save = screen.getByRole('button', { name: 'Save answer' });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(box, 'Use Huntress.');
    expect((save as HTMLButtonElement).disabled).toBe(false);
    api.list.mockResolvedValue(roadmap([item({ id: 'q1', key: 'q1', title: 'Ask me', needs: 'hal', note: 'Which vendor?', reply: 'Use Huntress.', reply_at: '2026-11-18T12:00:00Z', reply_by: 'hal@goliveoak.com' })]));
    await userEvent.click(save);
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('q1', { reply: 'Use Huntress.' }));
    expect(await screen.findByText('Saved Nov 18, 2026 by hal@goliveoak.com')).toBeTruthy();
  });
});
