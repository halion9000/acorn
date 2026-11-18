import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const calls: { url: string; init?: RequestInit }[] = [];
let people: unknown[] = [];
let tasks: unknown[] = [];

vi.mock('@/lib/auth-session', async (original) => {
  const real = await original<typeof import('@/lib/auth-session')>();
  return {
    ...real,
    authFetch: vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (init?.method) return json({}, url.includes('/tasks/start') ? 201 : 200);
      if (url.includes('/tasks')) return json(tasks);
      return json(people);
    }),
  };
});
vi.mock('@/components/mssp/ClientPicker', () => ({ ClientPicker: () => null, clientFromAddress: () => '' }));

import { PersonnelView, checklistSummary } from './PersonnelView';

const progress = (over: Partial<{ started: boolean; total: number; done: number; open: number; overdue: number }> = {}) => ({ started: false, total: 0, done: 0, open: 0, overdue: 0, ...over });

describe('how a checklist is worded', () => {
  it('says not started, how many are done and how many are overdue, or that all are done', () => {
    expect(checklistSummary(progress())).toBe('Not started');
    expect(checklistSummary(progress({ started: true, total: 7, done: 3, open: 4 }))).toBe('3 of 7 done');
    expect(checklistSummary(progress({ started: true, total: 7, done: 3, open: 4, overdue: 2 }))).toBe('3 of 7 done, 2 overdue');
    expect(checklistSummary(progress({ started: true, total: 7, done: 7, open: 0 }))).toBe('All 7 done');
  });
});

describe('the people page', () => {
  beforeEach(() => {
    calls.length = 0;
    people = [
      { email: 'ann@x.com', name: 'Ann Lee', active: true, onboarding: progress({ started: true, total: 7, done: 1, open: 6, overdue: 1 }), offboarding: progress() },
      { email: 'carl@x.com', name: null, active: false, onboarding: progress(), offboarding: progress({ started: true, total: 7, done: 7, open: 0 }) },
    ];
    tasks = [{ id: 't1', email: 'ann@x.com', kind: 'onboarding', title: 'Set up multi-factor authentication', due_on: '2026-11-20', done_at: null, done_by: null }];
  });

  it('lists each person with both checklists, and marks one who has left', async () => {
    render(<PersonnelView />);
    expect(await screen.findByText('Ann Lee')).toBeInTheDocument();
    expect(screen.getByText('Onboarding: 1 of 7 done, 1 overdue')).toBeInTheDocument();
    expect(screen.getByText('Offboarding: All 7 done')).toBeInTheDocument();
    expect(screen.getByText('no longer active')).toBeInTheDocument();
  });

  it('opens a person, starts the checklist that has no tasks, ticks a task off and adds one of their own', async () => {
    render(<PersonnelView />);
    await screen.findByText('Ann Lee');
    fireEvent.click(screen.getAllByRole('button', { name: 'Open' })[0]!);
    expect(await screen.findByLabelText('Set up multi-factor authentication')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Start offboarding' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/v1/personnel/ann%40x.com/tasks/start'))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith('/tasks/start'))!.init!.body))).toEqual({ kind: 'offboarding' });
    fireEvent.click(screen.getByLabelText('Set up multi-factor authentication'));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/v1/personnel/tasks/t1/done'))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith('/done'))!.init!.body))).toEqual({ done: true });
    const add = screen.getByRole('button', { name: 'Add task' });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText('A task of your own'), { target: { value: 'Return the badge' } });
    fireEvent.change(screen.getByLabelText('Checklist for the new task'), { target: { value: 'offboarding' } });
    fireEvent.click(add);
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST' && c.url.endsWith('/ann%40x.com/tasks'))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.init?.method === 'POST' && c.url.endsWith('/ann%40x.com/tasks'))!.init!.body))).toEqual({ kind: 'offboarding', title: 'Return the badge' });
  });
});
