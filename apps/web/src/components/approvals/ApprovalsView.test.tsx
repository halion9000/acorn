import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const listApprovals = vi.hoisted(() => vi.fn());
const approve = vi.hoisted(() => vi.fn());
const deny = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ responderApi: { listApprovals, approve, deny } }));

import { ApprovalsView, recordsOnly, requesterLabel } from './ApprovalsView';

const item = (over: Record<string, unknown> = {}) => ({
  id: 'a1',
  tenant_id: 't',
  run_id: null,
  case_id: null,
  alert_id: null,
  requested_by: 'toolbox:tech@liveoakit.com',
  required_user_id: null,
  required_topic: null,
  title: "Reset a person's MFA: ann@acme.com",
  summary: 'Remove their methods. Client: Acme.\nWhy: lost phone\nNot easily reversed.',
  risk_level: 'high',
  action: { kind: 'toolbox', tool: 'reset_mfa' },
  status: 'pending',
  decided_by_id: null,
  decided_at: null,
  decision_comment: null,
  expires_at: '2026-11-26T00:00:00Z',
  created_at: '2026-11-19T10:00:00Z',
  updated_at: '2026-11-19T10:00:00Z',
  ...over,
});

beforeEach(() => {
  listApprovals.mockReset();
  approve.mockReset();
  deny.mockReset();
  listApprovals.mockResolvedValue({ items: [item()] });
});
afterEach(() => cleanup());

describe('ApprovalsView', () => {
  it('lists what waits, says what approving does for a Toolbox request, and approves with a comment', async () => {
    render(<ApprovalsView />);
    expect(await screen.findByText("Reset a person's MFA: ann@acme.com")).toBeTruthy();
    expect(listApprovals).toHaveBeenCalledWith({ status: 'pending', page_size: 100 });
    expect(screen.getByText('Toolbox request from tech@liveoakit.com')).toBeTruthy();
    expect(screen.getByText(/Nothing runs yet/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText('Comment'), 'checked with the client');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(approve).toHaveBeenCalledWith('a1', 'checked with the client'));
    await waitFor(() => expect(listApprovals).toHaveBeenCalledTimes(2));
  });

  it('needs a reason to deny, and sends it', async () => {
    render(<ApprovalsView />);
    await screen.findByText("Reset a person's MFA: ann@acme.com");
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Say why you are denying it.');
    expect(deny).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText('Comment'), 'not our client');
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    await waitFor(() => expect(deny).toHaveBeenCalledWith('a1', 'not our client'));
  });

  it('shows the server reason when a decision is refused, and decided requests without buttons', async () => {
    approve.mockRejectedValue(new Error('API 409 Conflict - Approval already denied'));
    render(<ApprovalsView />);
    await screen.findByText("Reset a person's MFA: ann@acme.com");
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect((await screen.findByRole('alert')).textContent).toContain('409');
    cleanup();
    listApprovals.mockResolvedValue({ items: [item({ status: 'denied', decided_at: '2026-11-19T11:00:00Z', decision_comment: 'not our client' })] });
    render(<ApprovalsView />);
    expect(await screen.findByText(/not our client/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('asks for the other tabs by status', async () => {
    render(<ApprovalsView />);
    await screen.findByText("Reset a person's MFA: ann@acme.com");
    listApprovals.mockResolvedValue({ items: [] });
    await userEvent.click(screen.getByRole('button', { name: 'Approved' }));
    await waitFor(() => expect(listApprovals).toHaveBeenLastCalledWith({ status: 'approved', page_size: 100 }));
    expect(await screen.findByText('Nothing here.')).toBeTruthy();
  });
});

describe('helpers', () => {
  it('names a Toolbox requester and knows only Toolbox requests record the decision alone', () => {
    expect(requesterLabel('toolbox:a@b.co')).toBe('Toolbox request from a@b.co');
    expect(requesterLabel('agent:triage')).toBe('agent:triage');
    expect(recordsOnly({ action: { kind: 'toolbox' } })).toBe(true);
    expect(recordsOnly({ action: { kind: 'isolate_host' } })).toBe(false);
  });
});
