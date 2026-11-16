import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const summary = vi.hoisted(() => vi.fn());
const enrol = vi.hoisted(() => vi.fn());
const confirm = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('@/lib/auth-session', () => ({ revokeServerSession: vi.fn(), authFetch: vi.fn() }));
vi.mock('@/components/settings/TotpCard', () => ({ SetupQr: () => null }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    clientPortalApi: { summary: (...a: unknown[]) => summary(...a) },
    totpApi: { enrol: () => enrol(), confirm: (c: string) => confirm(c) },
  };
});

import { ClientPortalView, refusalKind } from './ClientPortalView';

const refusal = (status: number, detail: string) => Object.assign(new Error(detail), { status, body: JSON.stringify({ detail }) });
const data = () => ({
  client_name: 'Acme Dental',
  received_at: '2026-11-15T10:00:00Z',
  tickets: {
    created: 11,
    resolved: 9,
    created_per_month: 11,
    resolved_per_month: 9,
    first_response_minutes: 10,
    by_type: [{ type: 'Incident', tickets: 11 }],
    resolved_by_agent: [],
    open_now: { total: 3, critical: 1, high: 0 },
  },
  hours: { total_hours: 12.5, hours_per_month: 12.5, by_month: [{ month: '2026-10', hours: 12.5 }], by_type: [{ type: 'Support', hours: 12.5 }] },
  satisfaction: { responses: 5, positive: 4, neutral: 0, negative: 1, satisfied_percent: 80, recent: [] },
});

beforeEach(() => {
  summary.mockReset();
  enrol.mockReset();
  confirm.mockReset();
});
afterEach(() => cleanup());

describe('refusalKind', () => {
  it('tells a missing authenticator app from an unlinked company and from a staff sign-in', () => {
    expect(refusalKind(403, 'mfa_setup_required: set up an authenticator app')).toBe('mfa');
    expect(refusalKind(403, 'This page is for the client dashboard sign-in.')).toBe('not-client');
    expect(refusalKind(409, 'Your company is not linked')).toBe('unlinked');
    expect(refusalKind(500, 'boom')).toBe('other');
  });
});

describe('the client dashboard', () => {
  it('shows the company summary with no staff navigation and no client picker', async () => {
    summary.mockResolvedValue(data());
    render(<ClientPortalView />);
    expect(await screen.findByText('Your IT summary')).toBeTruthy();
    expect(screen.getAllByText(/Acme Dental/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('summary-tickets')).toBeTruthy();
    expect(screen.getByTestId('summary-hours')).toBeTruthy();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(summary).toHaveBeenCalledWith(3);
  });

  it('asks for a different period without ever naming a client', async () => {
    summary.mockResolvedValue(data());
    render(<ClientPortalView />);
    await screen.findByText('Your IT summary');
    await userEvent.click(screen.getByRole('button', { name: 'Last 6 months' }));
    await waitFor(() => expect(summary).toHaveBeenLastCalledWith(6));
  });

  it('holds the numbers back and walks the person through the authenticator app when the server asks for it', async () => {
    summary.mockRejectedValueOnce(refusal(403, 'mfa_setup_required: set up an authenticator app')).mockResolvedValue(data());
    enrol.mockResolvedValue({ secret: 'JBSWY3DP', otpauth_uri: 'otpauth://totp/x' });
    confirm.mockResolvedValue({ recovery_codes: ['aaaa-bbbb'] });
    render(<ClientPortalView />);
    expect(await screen.findByTestId('portal-mfa-setup')).toBeTruthy();
    expect(screen.queryByText('Your IT summary')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Set up the authenticator app' }));
    await userEvent.type(await screen.findByLabelText(/6-digit code/), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Turn it on' }));
    expect(await screen.findByTestId('portal-recovery')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /open the dashboard/ }));
    expect(await screen.findByText('Your IT summary')).toBeTruthy();
  });

  it('says plainly when the company is not linked yet', async () => {
    summary.mockRejectedValue(refusal(409, 'Your company is not linked to a HaloPSA client yet. Ask your IT provider.'));
    render(<ClientPortalView />);
    expect(await screen.findByText(/not linked to a HaloPSA client/)).toBeTruthy();
  });
});
