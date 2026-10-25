import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { ToolChecks, isStale, STALE_HOURS } from './ToolChecks';
import { SourceHealth, failureKind, sortRuns, type SweepRun } from './SourceHealth';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

beforeEach(() => authFetch.mockReset());
afterEach(() => vi.restoreAllMocks());

describe('ToolChecks with history and accepted risks', () => {
  const checks = [
    { key: 'ninjaone_antivirus', status: 'not_met', evidence: '3 of 12 have no antivirus', since: '2026-10-20T00:00:00Z' },
    { key: 'ninjaone_patching', status: 'partly', evidence: '1 of 8 behind', accepted: { reason: 'Replacing in January', accepted_at: '2026-10-21T00:00:00Z', expires_at: '2026-12-01T00:00:00Z' } },
    { key: 'ninjaone_unsupported_os', status: 'met', evidence: 'All 8 supported' },
  ];

  it('says since when a check has had its status and marks an accepted one with its reason and end date', () => {
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} />);
    expect(within(screen.getByTestId('check-ninjaone_antivirus')).getByText(/since/)).toBeInTheDocument();
    const accepted = screen.getByTestId('accepted-ninjaone_patching');
    expect(accepted).toHaveTextContent(/Accepted until/);
    expect(screen.getByText(/Reason: Replacing in January/)).toBeInTheDocument();
    expect(within(screen.getByTestId('check-ninjaone_unsupported_os')).queryByText(/since/)).toBeNull();
  });

  it('can hide the checks that are fine, and shows nothing when none is left', () => {
    const { rerender, container } = render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} onlyProblems />);
    expect(screen.queryByTestId('check-ninjaone_unsupported_os')).toBeNull();
    expect(screen.getByTestId('check-ninjaone_antivirus')).toBeInTheDocument();
    rerender(<ToolChecks tool="ninjaone" label="NinjaOne" checks={[checks[2]]} onlyProblems />);
    expect(container).toBeEmptyDOMElement();
  });

  it('warns when a tool has not updated for over 48 hours', () => {
    const old = new Date(Date.now() - (STALE_HOURS + 1) * 3_600_000).toISOString();
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} refreshedAt={old} />);
    expect(screen.getByTestId('ninjaone-stale')).toBeInTheDocument();
    expect(isStale(new Date().toISOString())).toBe(false);
    expect(isStale(null)).toBe(false);
  });

  it('loads a check\'s history on request', async () => {
    authFetch.mockImplementation(() => json({ client_id: 'c', rows: [{ key: 'ninjaone_antivirus', source: 'ninjaone', status: 'not_met', previous_status: 'met', evidence: '', observed_at: '2026-10-20T00:00:00Z' }] }));
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} clientId="c1" />);
    await userEvent.click(within(screen.getByTestId('check-ninjaone_antivirus')).getByText('History'));
    await waitFor(() => expect(screen.getByTestId('history-ninjaone_antivirus')).toHaveTextContent('Good → Problem'));
    expect(authFetch.mock.calls[0][0]).toBe('/api/v1/client-posture/c1/check-history?key=ninjaone_antivirus');
  });

  it('accepts a check with a reason and a number of days, then asks the page to reload', async () => {
    const answers = ['Client is retiring them', '60'];
    vi.spyOn(window, 'prompt').mockImplementation(() => answers.shift() ?? null);
    authFetch.mockImplementation(() => json({}));
    const onChanged = vi.fn();
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} clientId="c1" onChanged={onChanged} />);
    await userEvent.click(within(screen.getByTestId('check-ninjaone_antivirus')).getByText('Accept this'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [url, init] = authFetch.mock.calls[0];
    expect(url).toBe('/api/v1/client-posture/c1/acceptances/ninjaone_antivirus');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ reason: 'Client is retiring them', expires_in_days: 60 });
  });

  it('marks a check not applicable with a reason and no end date, and shows it as such', async () => {
    const prompt = vi.spyOn(window, 'prompt').mockImplementation(() => 'No firewall on site');
    authFetch.mockImplementation(() => json({}));
    const onChanged = vi.fn();
    const { rerender } = render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} clientId="c1" onChanged={onChanged} />);
    await userEvent.click(within(screen.getByTestId('check-ninjaone_antivirus')).getByText('Not applicable'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(JSON.parse(authFetch.mock.calls[0][1].body)).toEqual({ reason: 'No firewall on site', not_applicable: true });
    const na = [{ ...checks[0], accepted: { reason: 'No firewall on site', accepted_at: '2026-10-21T00:00:00Z', not_applicable: true } }];
    rerender(<ToolChecks tool="ninjaone" label="NinjaOne" checks={na} clientId="c1" />);
    expect(screen.getByTestId('accepted-ninjaone_antivirus')).toHaveTextContent('Not applicable');
    expect(screen.getByText('Applies after all')).toBeInTheDocument();
  });

  it('offers no accept button for a check that is fine, and removes an acceptance on request', async () => {
    authFetch.mockImplementation(() => json({}));
    const onChanged = vi.fn();
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={checks} clientId="c1" onChanged={onChanged} />);
    expect(within(screen.getByTestId('check-ninjaone_unsupported_os')).queryByText('Accept this')).toBeNull();
    await userEvent.click(within(screen.getByTestId('check-ninjaone_patching')).getByText('Stop accepting'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(authFetch.mock.calls[0][1].method).toBe('DELETE');
  });
});

describe('ToolChecks list and explanation', () => {
  const withItems = [{ key: 'ninjaone_antivirus', status: 'not_met', evidence: '2 of 12 have no antivirus', items: ['PC-ONE: none installed', 'PC-TWO: switched off'] }];

  it('lists the machines behind a check on request', async () => {
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={withItems} />);
    expect(screen.queryByTestId('items-ninjaone_antivirus')).toBeNull();
    await userEvent.click(screen.getByText('Which ones (2)'));
    const list = screen.getByTestId('items-ninjaone_antivirus');
    expect(within(list).getByText('PC-ONE: none installed')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Hide the list'));
    expect(screen.queryByTestId('items-ninjaone_antivirus')).toBeNull();
  });

  it('explains why a check matters and how to fix it, only for a check that has an explanation', async () => {
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={[...withItems, { key: 'made_up_check', status: 'partly', evidence: 'x' }]} />);
    expect(within(screen.getByTestId('check-made_up_check')).queryByText('What this means')).toBeNull();
    await userEvent.click(within(screen.getByTestId('check-ninjaone_antivirus')).getByText('What this means'));
    const help = screen.getByTestId('help-ninjaone_antivirus');
    expect(help).toHaveTextContent(/no working, up-to-date antivirus is unprotected/);
    expect(help).toHaveTextContent(/To fix: Install or switch on antivirus/);
  });

  it('offers no list link for a check that carries none', () => {
    render(<ToolChecks tool="ninjaone" label="NinjaOne" checks={[{ key: 'ninjaone_antivirus', status: 'met', evidence: 'fine' }]} />);
    expect(screen.queryByText(/Which ones/)).toBeNull();
  });
});

describe('failureKind', () => {
  it('says who to look at for each kind of first error', () => {
    expect(failureKind('Acme: fetch failed')).toBe('A.C.O.R.N could not be reached');
    expect(failureKind('Acme: A.C.O.R.N refused the checks (500)')).toBe('A.C.O.R.N could not be reached');
    expect(failureKind('Meraki refused the API key')).toBe('the tool refused the key');
    expect(failureKind('Huntress returned 403')).toBe('the tool refused the key');
    expect(failureKind('CIPP returned 429')).toBe('the tool is rate limiting CORE');
    expect(failureKind("api.huntress.io didn't answer within 30s")).toBe('the tool is slow or down');
    expect(failureKind('Huntress returned 504')).toBe('the tool is slow or down');
    expect(failureKind('something odd')).toBeNull();
    expect(failureKind('')).toBeNull();
  });
});

describe('SourceHealth', () => {
  const run = (source: string, health: string, over: Partial<SweepRun> = {}): SweepRun => ({ source, title: source, ran_at: '2026-10-25T00:00:00Z', accounts: 10, sent: 10, failed: 0, waiting: 0, skipped: 0, first_error: '', health, ...over });

  it('puts the failing sweeps first, then partly, stale and fine', () => {
    expect(sortRuns([run('a', 'ok'), run('b', 'stale'), run('c', 'failed'), run('d', 'partly')]).map((r) => r.source)).toEqual(['c', 'd', 'b', 'a']);
  });

  it('is open and says how many need a look when one is failing, with the reason', async () => {
    authFetch.mockImplementation(() => json([run('ninjaone', 'failed', { sent: 0, failed: 5, first_error: 'Acme: fetch failed' }), run('slide', 'ok')]));
    render(<SourceHealth />);
    await waitFor(() => expect(screen.getByTestId('source-health')).toBeInTheDocument());
    expect(screen.getByText(/1 of 2 need a look/)).toBeInTheDocument();
    expect(within(screen.getByTestId('sweep-ninjaone')).getByText(/Failing/)).toBeInTheDocument();
    expect(within(screen.getByTestId('sweep-ninjaone')).getByText(/fetch failed/)).toBeInTheDocument();
  });

  it('shows nothing when A.C.O.R.N has no run yet or the call fails', async () => {
    authFetch.mockImplementation(() => json([]));
    const { container } = render(<SourceHealth />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
