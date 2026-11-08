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
    expect(screen.getByTestId('nist-totals')).toHaveTextContent('1 met · 0 partly · 1 not met · 1 need a person');
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
