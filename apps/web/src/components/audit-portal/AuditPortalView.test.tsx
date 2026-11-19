import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const audits = vi.hoisted(() => vi.fn());
const get = vi.hoisted(() => vi.fn());
const patchRequest = vi.hoisted(() => vi.fn());
const files = vi.hoisted(() => vi.fn());
const upload = vi.hoisted(() => vi.fn());
const download = vi.hoisted(() => vi.fn());
const saveBlob = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('@/lib/auth-session', () => ({ revokeServerSession: vi.fn(), authFetch: vi.fn() }));
vi.mock('@/components/settings/TotpCard', () => ({ SetupQr: () => null }));
vi.mock('@/lib/fileBytes', async () => {
  const actual = await vi.importActual<typeof import('@/lib/fileBytes')>('@/lib/fileBytes');
  return { ...actual, saveBlob: (...a: unknown[]) => saveBlob(...a) };
});
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    auditPortalApi: {
      audits: () => audits(),
      get: (id: string) => get(id),
      patchRequest: (...a: unknown[]) => patchRequest(...a),
      files: (id: string) => files(id),
      upload: (...a: unknown[]) => upload(...a),
      download: (...a: unknown[]) => download(...a),
    },
    totpApi: { enrol: vi.fn(), confirm: vi.fn() },
  };
});

import { AuditPortalView, auditRefusal } from './AuditPortalView';

const refusal = (status: number, detail: string) => Object.assign(new Error(detail), { status, body: JSON.stringify({ detail }) });
const row = { id: 'a1', name: 'SOC 2 2026', framework: 'SOC2', auditor: null, period_start: null, period_end: null, status: 'fieldwork', requests: 2, open: 0, provided: 1, accepted: 1, overdue: 0, created_at: '2026-11-01T00:00:00Z' };
const detail = (over: Record<string, unknown> = {}) => ({
  ...row,
  ...over,
  items: [
    { id: 'r1', title: 'Access review evidence', control_id: null, owner: 'Hal', due_date: null, status: 'provided', overdue: false, note: '', link: null, updated_at: '2026-11-02T00:00:00Z' },
    { id: 'r2', title: 'Backup report', control_id: null, owner: null, due_date: null, status: 'open', overdue: false, note: '', link: null, updated_at: '2026-11-02T00:00:00Z' },
  ],
});
const file = { id: 'f1', name: 'policy.pdf', size_bytes: 2048, request_id: null, uploaded_by: 'hal@x.test', by_auditor: false, created_at: '2026-11-03T10:00:00Z' };

beforeEach(() => {
  for (const m of [audits, get, patchRequest, files, upload, download, saveBlob]) m.mockReset();
  audits.mockResolvedValue([row]);
  get.mockResolvedValue(detail());
  files.mockResolvedValue([file]);
});
afterEach(() => cleanup());

describe('auditRefusal', () => {
  it('tells a missing authenticator app from a staff sign-in', () => {
    expect(auditRefusal(403, 'mfa_setup_required: set up an authenticator app')).toBe('mfa');
    expect(auditRefusal(403, 'This page is for an auditor')).toBe('not-auditor');
    expect(auditRefusal(500, 'x')).toBe('other');
  });
});

describe('AuditPortalView', () => {
  it('opens the one audit it was invited to with its requests and files, and offers accept only where something was provided', async () => {
    render(<AuditPortalView />);
    const page = await screen.findByTestId('portal-audit');
    expect(within(page).getByText('SOC 2 2026')).toBeTruthy();
    const reqs = within(page).getAllByTestId('portal-request');
    expect(within(reqs[0]!).getByRole('button', { name: 'Accept Access review evidence' })).toBeTruthy();
    expect(within(reqs[1]!).queryByRole('button', { name: /Accept|Send back/ })).toBeNull(); // nothing provided yet
    expect(await within(page).findByText('policy.pdf')).toBeTruthy();
    expect(get).toHaveBeenCalledWith('a1');
  });

  it('accepts a request with a note and shows the updated request', async () => {
    patchRequest.mockResolvedValue(detail({ accepted: 2 }));
    render(<AuditPortalView />);
    const page = await screen.findByTestId('portal-audit');
    await userEvent.type(within(page).getByLabelText('Note on Access review evidence'), 'Looks complete');
    await userEvent.click(within(page).getByRole('button', { name: 'Accept Access review evidence' }));
    expect(patchRequest).toHaveBeenCalledWith('a1', 'r1', { status: 'accepted', note: 'Looks complete' });
    await waitFor(() => expect(within(page).getByText(/2 of 2 requests accepted/)).toBeTruthy());
  });

  it('uploads a file as base64 and downloads one through the save helper', async () => {
    upload.mockResolvedValue([file, { ...file, id: 'f2', name: 'questions.txt', by_auditor: true }]);
    download.mockResolvedValue(new Blob(['x']));
    render(<AuditPortalView />);
    const box = await screen.findByTestId('audit-files');
    await within(box).findByText('policy.pdf');
    await userEvent.upload(within(box).getByLabelText('Add a file'), new File(['hello'], 'questions.txt', { type: 'text/plain' }));
    await waitFor(() => expect(upload).toHaveBeenCalledWith('a1', { name: 'questions.txt', content_base64: btoa('hello') }));
    expect(await within(box).findByText('questions.txt')).toBeTruthy();
    await userEvent.click(within(box).getByRole('button', { name: 'Download policy.pdf' }));
    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), 'policy.pdf'));
    expect(download).toHaveBeenCalledWith('a1', 'f1');
  });

  it('takes no more files once the audit is complete, and hides accept and send back', async () => {
    get.mockResolvedValue(detail({ status: 'complete' }));
    audits.mockResolvedValue([{ ...row, status: 'complete' }]);
    render(<AuditPortalView />);
    const page = await screen.findByTestId('portal-audit');
    expect(within(page).queryByLabelText('Add a file')).toBeNull();
    expect(within(page).queryByRole('button', { name: /Accept/ })).toBeNull();
    expect(within(page).getByText(/complete and takes no more files/)).toBeTruthy();
  });

  it('asks for an authenticator app, and says so when this is not an auditor sign-in', async () => {
    audits.mockRejectedValue(refusal(403, 'mfa_setup_required: set up an authenticator app first'));
    render(<AuditPortalView />);
    expect(await screen.findByTestId('portal-mfa-setup')).toBeTruthy();
    cleanup();
    audits.mockRejectedValue(refusal(403, 'This page is for an auditor'));
    render(<AuditPortalView />);
    expect(await screen.findByText(/for auditor sign-ins/)).toBeTruthy();
  });

  it('lists several audits to choose from and says when none were opened', async () => {
    audits.mockResolvedValue([row, { ...row, id: 'a2', name: 'ISO 2026' }]);
    get.mockResolvedValue(detail({ id: 'a2', name: 'ISO 2026' }));
    render(<AuditPortalView />);
    const list = await screen.findByTestId('portal-audit-list');
    await userEvent.click(within(list).getByRole('button', { name: /ISO 2026/ }));
    expect(await screen.findByTestId('portal-audit')).toBeTruthy();
    cleanup();
    audits.mockResolvedValue([]);
    render(<AuditPortalView />);
    expect(await screen.findByText(/No audit has been opened to you yet/)).toBeTruthy();
  });
});
