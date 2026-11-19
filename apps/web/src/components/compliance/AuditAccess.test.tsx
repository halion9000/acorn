import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const auditors = vi.hoisted(() => vi.fn());
const invite = vi.hoisted(() => vi.fn());
const unlink = vi.hoisted(() => vi.fn());
const files = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch: vi.fn() }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    auditAccessApi: {
      auditors: (...a: unknown[]) => auditors(...a),
      invite: (...a: unknown[]) => invite(...a),
      unlink: (...a: unknown[]) => unlink(...a),
      files: (...a: unknown[]) => files(...a),
      remove: (...a: unknown[]) => remove(...a),
      upload: vi.fn(),
      download: vi.fn(),
    },
  };
});

import { ApiError } from '@/lib/api';
import { AuditAccess } from './AuditAccess';

const pat = { user_id: 'u1', email: 'pat@auditfirm.test', name: 'Pat', since: '2026-11-18T10:00:00Z' };
const file = { id: 'f1', name: 'policy.pdf', size_bytes: 2048, request_id: null, uploaded_by: 'hal@x.test', by_auditor: false, created_at: '2026-11-03T10:00:00Z' };

beforeEach(() => {
  for (const m of [auditors, invite, unlink, files, remove]) m.mockReset();
  auditors.mockResolvedValue([]);
  files.mockResolvedValue([file]);
});
afterEach(() => cleanup());

describe('AuditAccess', () => {
  it('says no auditor can open the audit yet and keeps the create button off until an account name is typed', async () => {
    render(<AuditAccess clientId="" auditId="a1" complete={false} />);
    expect(await screen.findByTestId('no-auditors')).toBeTruthy();
    const create = screen.getByRole('button', { name: 'Create the auditor sign-in' }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText('Account name'), 'pat-audit');
    expect(create.disabled).toBe(false);
  });

  it('creates the sign-in, shows the temporary password once and lists the auditor', async () => {
    invite.mockResolvedValue({ auditors: [pat], temporary_password: 'Tmp-Pass-123' });
    render(<AuditAccess clientId="c1" auditId="a1" complete={false} />);
    await screen.findByTestId('no-auditors');
    await userEvent.type(screen.getByLabelText('Account name'), 'pat-audit');
    await userEvent.type(screen.getByLabelText('E-mail (optional)'), 'pat@auditfirm.test');
    await userEvent.click(screen.getByRole('button', { name: 'Create the auditor sign-in' }));
    expect(invite).toHaveBeenCalledWith('c1', 'a1', { account_name: 'pat-audit', email: 'pat@auditfirm.test', name: null });
    expect((await screen.findByTestId('temp-password')).textContent).toContain('Tmp-Pass-123');
    expect(within(await screen.findByTestId('auditor')).getByText(/Pat/)).toBeTruthy();
  });

  it('removes an auditor and shows the server\'s refusal', async () => {
    auditors.mockResolvedValue([pat]);
    unlink.mockResolvedValue([]);
    render(<AuditAccess clientId="" auditId="a1" complete={false} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Remove access for Pat' }));
    expect(unlink).toHaveBeenCalledWith('', 'a1', 'u1');
    expect(await screen.findByTestId('no-auditors')).toBeTruthy();
    invite.mockRejectedValue(new ApiError('API 409', 409, JSON.stringify({ detail: 'That account name is already taken. Choose another.' })));
    await userEvent.type(screen.getByLabelText('Account name'), 'taken-one');
    await userEvent.click(screen.getByRole('button', { name: 'Create the auditor sign-in' }));
    expect(await screen.findByText('That account name is already taken. Choose another.')).toBeTruthy();
  });

  it('lets staff remove a file, and a complete audit offers no new sign-in and no removal', async () => {
    remove.mockResolvedValue([]);
    render(<AuditAccess clientId="" auditId="a1" complete={false} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Remove policy.pdf' }));
    expect(remove).toHaveBeenCalled();
    expect(await screen.findByTestId('audit-files-empty')).toBeTruthy();
    cleanup();
    render(<AuditAccess clientId="" auditId="a1" complete />);
    await screen.findByText('policy.pdf');
    expect(screen.queryByRole('button', { name: 'Create the auditor sign-in' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove policy.pdf' })).toBeNull();
    await waitFor(() => expect(screen.getByText(/complete and takes no more files/)).toBeTruthy());
  });
});
