import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PolicyAssign, assignmentLine } from './PolicyAssign';

const rows = [
  { email: 'ann@x.com', name: 'Ann', due_on: '2026-12-01', assigned_by: 'hal@x', state: 'pending', reminders_sent: 2, last_reminded_on: '2026-11-17' },
  { email: 'bob@x.com', name: null, due_on: '2026-12-01', assigned_by: 'hal@x', state: 'accepted', reminders_sent: 0, last_reminded_on: null },
];
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }));

describe('Assigning a policy', () => {
  it('words each line: who, the state, the day and how often they were reminded', () => {
    expect(assignmentLine(rows[0]!)).toBe('Ann (ann@x.com) · pending, due 2026-12-01, reminded 2 times');
    expect(assignmentLine({ ...rows[0]!, reminders_sent: 1, name: null })).toBe('ann@x.com · pending, due 2026-12-01, reminded 1 time');
    expect(assignmentLine({ ...rows[0]!, reminders_sent: 0, state: 'overdue' })).toContain('overdue, due 2026-12-01, not reminded yet');
    expect(assignmentLine(rows[1]!)).toBe('bob@x.com · accepted');
  });

  it('lists who is assigned, assigns everyone with a due day, assigns pasted addresses and removes one', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((url: string, init?: RequestInit) => (init?.method === 'POST' ? json(rows, 201) : init?.method === 'DELETE' ? Promise.resolve(new Response(null, { status: 204 })) : json(rows)));
    const changed = vi.fn();
    render(<PolicyAssign itemId="i1" scoped={scoped} onChange={changed} />);
    expect(await screen.findByLabelText('Assigned people')).toHaveTextContent('Ann (ann@x.com) · pending');
    await user.type(screen.getByLabelText('Due day'), '2026-12-15');
    await user.click(screen.getByRole('button', { name: 'Assign to everyone' }));
    await waitFor(() => expect(JSON.parse(scoped.mock.calls.find(([, i]) => i?.method === 'POST')![1]!.body as string)).toEqual({ emails: [], everyone: true, due_on: '2026-12-15' }));
    await user.type(screen.getByLabelText('Addresses to assign'), 'cy@x.com, dee@x.com');
    await user.click(screen.getByRole('button', { name: 'Assign 2 people' }));
    await waitFor(() => expect(scoped.mock.calls.filter(([, i]) => i?.method === 'POST')).toHaveLength(2));
    expect(JSON.parse(scoped.mock.calls.filter(([, i]) => i?.method === 'POST')[1]![1]!.body as string)).toEqual({ emails: ['cy@x.com', 'dee@x.com'], everyone: false, due_on: '2026-12-15' });
    await user.click(screen.getByRole('button', { name: 'Take the policy off ann@x.com' }));
    await waitFor(() => expect(scoped.mock.calls.some(([u, i]) => String(u).endsWith('/assignments/ann%40x.com') && i?.method === 'DELETE')).toBe(true));
    expect(changed).toHaveBeenCalled();
  });

  it('says why when assigning is refused', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json({ detail: 'Save the text of the policy first; there is nothing to read yet.' }, 422) : json([])));
    render(<PolicyAssign itemId="i1" scoped={scoped} />);
    await user.click(await screen.findByRole('button', { name: 'Assign to everyone' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('nothing to read yet');
  });
});
