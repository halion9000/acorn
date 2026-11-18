import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { PolicyApproval, approvalBadge, approvalLine, type Approval } from './PolicyApproval';

const row = (over: Partial<Approval> = {}): Approval => ({
  id: 'r1',
  version: 2,
  approver: 'bob@x.com',
  requested_by: 'amy@x.com',
  requested_at: '2026-11-16T10:00:00Z',
  note: '',
  decision: 'pending',
  decided_by: null,
  decided_at: null,
  comment: '',
  ...over,
});

describe('how a request is worded', () => {
  it('says who it waits on, who approved it and when, or who rejected it and why', () => {
    expect(approvalLine(row())).toBe('Version 2: waiting for bob@x.com (asked by amy@x.com on 2026-11-16)');
    expect(approvalLine(row({ decision: 'approved', decided_by: 'bob@x.com', decided_at: '2026-11-17T09:00:00Z' }))).toBe('Version 2: approved by bob@x.com on 2026-11-17');
    expect(approvalLine(row({ decision: 'rejected', decided_by: 'bob@x.com', decided_at: '2026-11-17T09:00:00Z', comment: 'backups missing' }))).toBe('Version 2: rejected by bob@x.com on 2026-11-17: backups missing');
  });
  it('has a badge for every state, and one for a version nobody has been asked about', () => {
    expect([undefined, 'none', 'pending', 'approved', 'rejected'].map(approvalBadge)).toEqual(['Not sent for approval', 'Not sent for approval', 'Waiting for approval', 'Approved', 'Rejected']);
  });
});

function setup(rows: Approval[], answer: (url: string, init?: RequestInit) => Response = () => new Response('{}', { status: 200 })) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const scoped = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (!init || !init.method) return new Response(JSON.stringify(rows), { status: 200 });
    return answer(url, init);
  });
  render(<PolicyApproval itemId="p1" scoped={scoped} />);
  return calls;
}

describe('the approval box', () => {
  it('lists the requests and sends a new one to the named person', async () => {
    const calls = setup([row()]);
    expect(await screen.findByText(/waiting for bob@x.com/)).toBeInTheDocument();
    const ask = screen.getByRole('button', { name: /Ask for approval/ });
    expect(ask).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Approver's e-mail address"), { target: { value: ' eve@x.com ' } });
    fireEvent.change(screen.getByLabelText('Note for the approver'), { target: { value: 'section 3 please' } });
    fireEvent.click(ask);
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.init?.method === 'POST')!;
    expect(post.url).toBe('/api/v1/governance/p1/approvals');
    expect(JSON.parse(String(post.init!.body))).toEqual({ approver_email: 'eve@x.com', note: 'section 3 please' });
  });

  it('sends approve and reject for that request, with the reason typed, and shows the reason the server gives when it refuses', async () => {
    const calls = setup([row()], () => new Response(JSON.stringify({ detail: 'Only the person named can decide.' }), { status: 403 }));
    await screen.findByText(/waiting for bob@x.com/);
    fireEvent.change(screen.getByLabelText('Reason for version 2'), { target: { value: 'too vague' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only the person named can decide.');
    const post = calls.find((c) => c.init?.method === 'POST')!;
    expect(post.url).toBe('/api/v1/governance/p1/approvals/r1/decision');
    expect(JSON.parse(String(post.init!.body))).toEqual({ decision: 'rejected', comment: 'too vague' });
  });

  it('has no Approve or Reject on a request that is already decided', async () => {
    setup([row({ decision: 'approved', decided_by: 'bob@x.com', decided_at: '2026-11-17T09:00:00Z' })]);
    expect(await screen.findByText(/approved by bob@x.com/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
  });
});
