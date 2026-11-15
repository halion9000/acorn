import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), roadmapApi: api }));

import { RoadmapView, visibleItems } from './RoadmapView';

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
