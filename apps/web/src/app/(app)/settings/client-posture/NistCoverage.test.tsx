import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { NistCoverage } from './NistCoverage';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

const data = {
  controls: [
    { control_id: 'DE.AE-02', category: 'Detect', title: 'Events analysed', status: 'met', met_since: '2026-10-01T00:00:00Z', checks: [{ key: 'huntress_protection', status: 'met', evidence: '45 of 50 machines' }] },
    { control_id: 'PR.AA-03', category: 'Protect', title: 'Users authenticated', status: 'not_met', met_since: null, checks: [{ key: 'legacy_auth_ca', status: 'not_met', evidence: 'no policy blocks legacy sign-in' }] },
    { control_id: 'GV.OC-01', category: 'Govern', title: 'Mission', status: 'no_evidence', met_since: null, checks: [] },
  ],
  totals: { met: 1, partly: 0, not_met: 1, no_evidence: 1 },
};

beforeEach(() => authFetch.mockReset());

describe('NistCoverage', () => {
  it('shows each control with its standing, the totals, and "met since" only for a met one', async () => {
    authFetch.mockImplementation(() => json(data));
    render(<NistCoverage clientId="c1" />);
    expect(await screen.findByTestId('nist-DE.AE-02')).toHaveTextContent('Met since 2026-10-01');
    expect(screen.getByTestId('nist-PR.AA-03')).toHaveTextContent('Not met');
    expect(screen.getByTestId('nist-PR.AA-03')).not.toHaveTextContent('since');
    expect(screen.getByTestId('nist-GV.OC-01')).toHaveTextContent('No automated evidence');
    expect(screen.getByTestId('nist-totals')).toHaveTextContent(/1 met \(\d+ for 90\+ days\) · 0 partly · 1 not met · 1 need a person/);
    expect(authFetch).toHaveBeenCalledWith('/api/v1/nist-coverage/c1');
  });

  it('opens a control to show the checks behind it, or says a person provides the evidence when there are none', async () => {
    authFetch.mockImplementation(() => json(data));
    const user = userEvent.setup();
    render(<NistCoverage clientId="c1" />);
    await user.click(await screen.findByRole('button', { name: /PR\.AA-03/ }));
    expect(screen.getByTestId('nist-PR.AA-03')).toHaveTextContent('legacy auth ca: no policy blocks legacy sign-in');
    await user.click(screen.getByRole('button', { name: /GV\.OC-01/ }));
    expect(screen.getByTestId('nist-GV.OC-01')).toHaveTextContent('A person provides the evidence');
  });

  it('shows nothing when the API does not have the route', async () => {
    authFetch.mockImplementation(() => json({}, 404));
    render(<NistCoverage clientId="c1" />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('nist')).toBeNull();
  });
});

describe("daysMet", () => {
  const now = Date.parse("2026-11-08T00:00:00Z");
  it("counts whole days since the date, and is null for no date, a bad date or a future one", async () => {
    const { daysMet } = await import("./NistCoverage");
    expect(daysMet("2026-08-10T00:00:00Z", now)).toBe(90);
    expect(daysMet("2026-11-07T12:00:00Z", now)).toBe(0);
    expect(daysMet(null, now)).toBeNull();
    expect(daysMet("not a date", now)).toBeNull();
    expect(daysMet("2027-01-01T00:00:00Z", now)).toBeNull();
  });
});

describe('NistCoverage: what to do about a check that is not met', () => {
  it('shows the fix under a not-met or partly-met check that has advice, and none under a met check or one with no advice', async () => {
    const { CHECK_HELP } = await import('./checkHelp');
    const known = Object.keys(CHECK_HELP)[0];
    authFetch.mockImplementation(() =>
      json({
        controls: [
          {
            control_id: 'PR.PS-02',
            category: 'Protect',
            title: 'Software maintained',
            status: 'not_met',
            met_since: null,
            checks: [
              { key: known, status: 'not_met', evidence: 'behind' },
              { key: 'no_advice_for_this_one', status: 'not_met', evidence: 'x' },
            ],
          },
          { control_id: 'DE.CM-01', category: 'Detect', title: 'Monitored', status: 'met', met_since: '2026-10-01T00:00:00Z', checks: [{ key: known, status: 'met', evidence: 'fine' }] },
        ],
        totals: { met: 1, partly: 0, not_met: 1, no_evidence: 0 },
      }),
    );
    const user = userEvent.setup();
    render(<NistCoverage clientId="c1" />);
    await user.click(await screen.findByRole('button', { name: /PR\.PS-02/ }));
    expect(screen.getByTestId(`nist-fix-${known}`)).toHaveTextContent(`To fix: ${CHECK_HELP[known].fix}`);
    expect(screen.queryByTestId('nist-fix-no_advice_for_this_one')).toBeNull();
    await user.click(screen.getByRole('button', { name: /DE\.CM-01/ }));
    expect(screen.getByTestId('nist-DE.CM-01')).toHaveTextContent('fine');
    expect(screen.queryByTestId(`nist-fix-${known}`)).toBeNull(); // the met check has no "To fix" line
  });
});
