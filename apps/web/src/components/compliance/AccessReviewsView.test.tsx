import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), start: vi.fn(), decide: vi.fn(), decideAll: vi.fn(), complete: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), accessReviewsApi: api, msspApi: { listChildren: async () => [] } }));

import { AccessReviewsView } from './AccessReviewsView';

const row = (over: Record<string, unknown> = {}) => ({
  id: 'r1', name: 'Q4 access review', system: 'Microsoft 365', reviewer: 'Hal', due_date: '2026-12-01', status: 'open', overdue: false, summary: '', people: 3, pending: 3, keep: 0, remove: 0,
  flagged: 1, created_at: '2026-11-14T10:00:00Z', completed_at: null, completed_by: null, ...over,
});
const entry = (over: Record<string, unknown> = {}) => ({ id: 'e1', person: 'boss@acme.com', name: null, access: 'Microsoft 365, administrator', flags: ['administrator'], decision: 'pending', note: '', decided_by: null, decided_at: null, ...over });
const detail = (over: Record<string, unknown> = {}) => ({ ...row(), entries: [entry(), entry({ id: 'e2', person: 'ok@acme.com', flags: [], access: 'Microsoft 365, member' })], ...over });
const list = (reviews = [row()]) => ({ reviews, systems: [{ system: 'Microsoft 365', people: 3 }] });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue(list());
  api.get.mockResolvedValue(detail());
  window.history.replaceState(null, '', '/compliance/access-reviews');
});

describe('AccessReviewsView', () => {
  it('lists the reviews with their due date, progress and status', async () => {
    api.list.mockResolvedValue(list([row({ overdue: true, pending: 1 }), row({ id: 'r2', name: 'Done one', status: 'complete', pending: 0 })]));
    render(<AccessReviewsView />);
    const rows = await screen.findAllByTestId('review-row');
    expect(rows[0]).toHaveTextContent('Q4 access review');
    expect(rows[0]).toHaveTextContent('2 of 3 decided');
    expect(rows[0]).toHaveTextContent('Overdue');
    expect(rows[1]).toHaveTextContent('Complete');
  });

  it('opens a review with the flagged people first, decides for each person and for everyone unflagged, and completes only when nobody is waiting', async () => {
    api.decide.mockResolvedValue(detail({ pending: 1, keep: 1 }));
    api.decideAll.mockResolvedValue(detail({ pending: 1, keep: 1 }));
    api.complete.mockResolvedValue(detail({ status: 'complete', pending: 0, summary: '3 people reviewed', completed_at: '2026-11-14T10:00:00Z', completed_by: 'hal@goliveoak.com' }));
    vi.spyOn(window, 'prompt').mockReturnValue('left in March');
    render(<AccessReviewsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Q4 access review' }));
    const entries = await screen.findAllByTestId('review-entry');
    expect(entries[0]).toHaveTextContent('boss@acme.com');
    expect(entries[0]).toHaveTextContent('administrator');
    expect(screen.getByTestId('review-progress')).toHaveTextContent('3 people: 0 keep, 0 remove, 3 waiting for a decision. 1 flagged');
    expect((screen.getByRole('button', { name: 'Complete the review' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Keep everyone without a flag' }));
    await waitFor(() => expect(api.decideAll).toHaveBeenCalledWith('', 'r1', 'keep'));
    await userEvent.click(screen.getByRole('button', { name: 'Keep ok@acme.com' }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith('', 'r1', 'e2', 'keep'));
    await userEvent.click(screen.getByRole('button', { name: 'Remove boss@acme.com' }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith('', 'r1', 'e1', 'remove', 'left in March'));
  });

  it('a completed review shows who completed it and what was decided, with no buttons to change it', async () => {
    api.get.mockResolvedValue(
      detail({ status: 'complete', pending: 0, keep: 2, remove: 1, summary: '3 people reviewed: 2 keep their access, 1 to have it removed.', completed_at: '2026-11-14T10:00:00Z', completed_by: 'hal@goliveoak.com', entries: [entry({ decision: 'remove' }), entry({ id: 'e2', decision: 'keep', flags: [] })] }),
    );
    render(<AccessReviewsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Q4 access review' }));
    const box = await screen.findByTestId('review-detail');
    expect(box).toHaveTextContent('Completed 2026-11-14 by hal@goliveoak.com');
    expect(within(box).queryByRole('button', { name: /^Keep / })).toBeNull();
    expect(within(box).queryByRole('button', { name: 'Complete the review' })).toBeNull();
  });

  it('starts a review for a system A.C.O.R.N holds people for, and asks for names for one it does not', async () => {
    api.start.mockResolvedValue(detail());
    render(<AccessReviewsView />);
    await screen.findByTestId('review-row');
    await userEvent.click(screen.getByRole('button', { name: 'Start a review' }));
    await userEvent.type(await screen.findByLabelText('Name of the review'), 'Q1 review');
    await userEvent.type(screen.getByLabelText('System'), 'Door badges');
    const people = await screen.findByLabelText('People');
    await userEvent.type(people, 'Dana{enter}Lee');
    await userEvent.click(screen.getByRole('button', { name: 'Take the snapshot and start' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith('', { name: 'Q1 review', system: 'Door badges', reviewer: null, due_date: null, people: ['Dana', 'Lee'] }));
  });

  it('says so when there are no reviews, and shows the reason when the list cannot be loaded', async () => {
    api.list.mockResolvedValue(list([]));
    const { unmount } = render(<AccessReviewsView />);
    expect(await screen.findByTestId('reviews-empty')).toBeTruthy();
    unmount();
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<AccessReviewsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});
