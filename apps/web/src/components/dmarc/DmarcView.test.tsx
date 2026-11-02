import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DmarcView, policyLabel, rateTone } from './DmarcView';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const status = { configured: true, mailbox: 'lodmarc@goliveoak.com', last_run_at: new Date().toISOString(), last_error: null, stored: 14, rejected: 0, unmatched_reports: 0 };
const row = (over: Record<string, unknown> = {}) => ({ client_id: 'c1', client_name: 'Acme', matched: true, domain: 'acme.com', reports: 4, total: 200, passed: 190, failed: 10, pass_rate: 95, policy: 'none', last_report: '2026-11-02T00:00:00Z', ...over });
let overview: Record<string, unknown>;
let setup: Record<string, unknown>;
let detail: Record<string, unknown>;

const view = () => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
    <DmarcView />
  </SWRConfig>
);

beforeEach(() => {
  overview = { days: 30, status, domains: [row()] };
  setup = { mailbox: 'lodmarc@goliveoak.com', mailbox_domain: 'goliveoak.com', lines: [{ client_id: 'c1', client_name: 'Acme Dental', domain: 'acmedental.com', alias: 'acme-dental@goliveoak.com', client_dmarc_rua: 'rua=mailto:acme-dental@goliveoak.com', authorization_record_name: 'acmedental.com._report._dmarc.goliveoak.com', authorization_record_value: 'v=DMARC1' }] };
  detail = { domain: 'acme.com', days: 30, reports: 4, total: 200, passed: 190, failed: 10, policy: 'none', series: [{ day: '2026-11-01', total: 100, passed: 95, failed: 5 }, { day: '2026-11-02', total: 100, passed: 95, failed: 5 }], failing_sources: [{ ip: '9.9.9.9', count: 10, header_from: 'acme.com', envelope_from: 'evil.example', disposition: 'quarantine' }] };
  authFetch.mockReset();
  authFetch.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/v1/dmarc/overview')) return json(200, overview);
    if (url.startsWith('/api/v1/dmarc/setup')) return json(200, setup);
    if (url.startsWith('/api/v1/dmarc/domains/')) return json(200, detail);
    return json(404, {});
  });
});

describe('the helpers', () => {
  it('colours the pass rate: healthy from 98, a look from 90, a problem below, none without mail', () => {
    expect([rateTone(99), rateTone(98), rateTone(97.9), rateTone(90), rateTone(89.9), rateTone(null)]).toEqual(['text-emerald-300', 'text-emerald-300', 'text-amber-300', 'text-amber-300', 'text-red-300', 'text-gray-400']);
  });
  it('says what a policy does in plain words', () => {
    expect([policyLabel('none'), policyLabel('quarantine'), policyLabel('reject')]).toEqual(['Monitor only', 'Quarantine', 'Reject']);
  });
});

describe('DMARC results', () => {
  it('lists each client domain with its messages, pass rate and policy, and says when the mailbox was read', async () => {
    overview.domains = [row({ client_name: 'Birch', domain: 'birch.com', total: 50, passed: 10, failed: 40, pass_rate: 20 }), row()];
    render(view());
    const rows = await screen.findAllByTestId('dmarc-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('20%')).toHaveClass('text-red-300');
    expect(within(rows[1]).getByText('95%')).toHaveClass('text-amber-300');
    expect(within(rows[1]).getByText('Monitor only')).toBeInTheDocument();
    expect(screen.getByText(/Reading/)).toHaveTextContent('lodmarc@goliveoak.com');
    expect(screen.getByText(/14 reports stored/)).toBeInTheDocument();
  });

  it('opening a domain shows its daily bars and the sources failing DMARC', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    const panel = await screen.findByRole('region', { name: 'acme.com detail' });
    expect(within(panel).getByRole('img', { name: /Messages per day/ })).toBeInTheDocument();
    expect(within(panel).getByText('9.9.9.9')).toBeInTheDocument();
    expect(within(panel).getByText('evil.example')).toBeInTheDocument();
    expect(within(panel).getByText('quarantine')).toBeInTheDocument();
  });

  it('says plainly when nothing has failed', async () => {
    detail.failing_sources = [];
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    expect(await screen.findByText('Nothing failed in this period.')).toBeInTheDocument();
  });

  it('shows the last read error and the reports that could not be matched', async () => {
    overview.status = { ...status, last_error: 'HTTP 403 ErrorAccessDenied', unmatched_reports: 2 };
    overview.domains = [row({ client_name: 'Not matched to a client', matched: false, domain: 'unknown.example' })];
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 403 ErrorAccessDenied');
    expect(screen.getByText(/2 reports could not be matched to a client/)).toBeInTheDocument();
  });

  it('with no mailbox set up says so and with no reports explains when they will arrive', async () => {
    overview.status = { ...status, configured: false, mailbox: null };
    overview.domains = [];
    render(view());
    expect(await screen.findByRole('status')).toHaveTextContent(/not set up on the server yet/);
    expect(screen.getByText(/No reports in the last 30 days/)).toBeInTheDocument();
  });

  it('changing the period asks for that period', async () => {
    render(view());
    await screen.findAllByTestId('dmarc-row');
    await userEvent.selectOptions(screen.getByLabelText('Period'), '90 days');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/dmarc/overview?days=90'));
  });

  it('shows the refusal when the person may not read them', async () => {
    authFetch.mockImplementation(async () => json(403, {}));
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to DMARC reports.');
  });
});

describe('DMARC setup', () => {
  it('gives each client domain its DMARC record value and the DNS line for your zone, ready to copy', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    const r = await screen.findByTestId('setup-row');
    expect(within(r).getByText('rua=mailto:acme-dental@goliveoak.com')).toBeInTheDocument();
    expect(within(r).getByText('acmedental.com._report._dmarc.goliveoak.com')).toBeInTheDocument();
    await userEvent.click(within(r).getByRole('button', { name: 'Copy the DNS record for acmedental.com' }));
    expect(write).toHaveBeenCalledWith('acmedental.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1');
    await userEvent.click(within(r).getByRole('button', { name: 'Copy the DMARC record value for acmedental.com' }));
    expect(write).toHaveBeenCalledWith('rua=mailto:acme-dental@goliveoak.com');
  });

  it('says what to do first when the mailbox is not set up, and when no client domains are known', async () => {
    setup = { mailbox: null, mailbox_domain: null, lines: [] };
    const first = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByText(/Set up the shared mailbox on the server first/)).toBeInTheDocument();
    first.unmount();
    setup = { mailbox: 'lodmarc@goliveoak.com', mailbox_domain: 'goliveoak.com', lines: [] };
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByText(/No client domains are known yet/)).toBeInTheDocument();
  });
});
