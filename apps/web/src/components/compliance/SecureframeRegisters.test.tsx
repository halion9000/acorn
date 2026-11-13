import { cleanup, render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { SecureframeRegisters, acceptancePercent, riskRating, riskScore } from './SecureframeRegisters';

const json = (body: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 403, json: () => Promise.resolve(body) });
const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SecureframeRegisters />
    </SWRConfig>,
  );

const POLICIES = [
  { name: 'Access Control Policy', status: 'published', published_at: '2026-05-01T00:00:00Z', accepted: 4, eligible: 10, frameworks: ['NIST CSF 2.0'] },
  { name: 'Acceptable Use Policy', status: 'published', published_at: '2026-04-01T00:00:00Z', accepted: 10, eligible: 10, frameworks: [] },
  { name: 'Vendor Policy', status: 'draft', published_at: null, accepted: 0, eligible: 0 },
];
const RISKS = [
  { id: 'R-2', description: 'A key vendor has an outage.', status: 'completed', treatment: 'accept', categories: ['Operational'], impact: 4, likelihood: 4, residual_impact: 4, residual_likelihood: 3 },
  { id: null, description: 'A laptop with client data is lost.', status: 'in_progress', treatment: 'mitigate', impact: 4, likelihood: 3, residual_impact: null, residual_likelihood: null },
];

beforeEach(() => authFetch.mockReset());
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('works out the share that accepted a policy, and says nothing when nobody has to', () => {
    expect([acceptancePercent({ accepted: 4, eligible: 10 }), acceptancePercent({ accepted: 10, eligible: 10 }), acceptancePercent({ accepted: 99, eligible: 12 }), acceptancePercent({ accepted: 0, eligible: 0 })]).toEqual([40, 100, 100, null]);
  });

  it('rates a risk as impact times likelihood, and a dash when it was not rated', () => {
    expect([riskScore(4, 3), riskScore(null, 3), riskScore(4, undefined)]).toEqual([12, null, null]);
    expect([riskRating(4, 3), riskRating(null, null)]).toEqual(['12 (impact 4 × likelihood 3)', '—']);
  });
});

describe('SecureframeRegisters', () => {
  it('lists each policy with its status and how many accepted it, and counts the ones still waiting', async () => {
    authFetch.mockImplementation(() => json({ report: { policy_list: POLICIES, risk_list: [] } }));
    show();
    expect(await screen.findByTestId('policies-summary')).toHaveTextContent('3 policies: 1 not yet accepted by everyone who must, 1 not published.');
    const rows = screen.getAllByTestId('policy-row').map((r) => r.textContent);
    expect(rows[0]).toContain('Access Control PolicyNIST CSF 2.0published4 of 10 (40%)');
    expect(rows[0]).toContain('2026-05-01');
    expect(rows[1]).toContain('Acceptable Use Policypublished10 of 10 (100%)');
    expect(rows[2]).toContain('Vendor Policydraftnobody has to');
    expect(screen.queryByTestId('risks-summary')).toBeNull();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/secureframe');
  });

  it('lists the risk register with the decision and the rating before and after treatment', async () => {
    authFetch.mockImplementation(() => json({ report: { policy_list: [], risk_list: RISKS } }));
    show();
    expect(await screen.findByTestId('risks-summary')).toHaveTextContent('2 risks: 1 being mitigated, 1 accepted.');
    const rows = screen.getAllByTestId('risk-row').map((r) => r.textContent);
    expect(rows[0]).toBe('R-2A key vendor has an outage.Operationalacceptcompleted16 (impact 4 × likelihood 4)12 (impact 4 × likelihood 3)');
    expect(rows[1]).toBe('A laptop with client data is lost.mitigatein progress12 (impact 4 × likelihood 3)—');
    expect(screen.queryByTestId('policies-summary')).toBeNull();
  });

  it('shows nothing when Secureframe is not connected, the lists were not sent, or the page may not read them', async () => {
    for (const answer of [json({ report: null }), json({ report: { policies: 44, risks: 6 } }), json({ report: { policy_list: [], risk_list: [] } }), json({}, false)]) {
      authFetch.mockImplementation(() => answer);
      const view = show();
      await new Promise((r) => setTimeout(r, 20));
      expect(view.container.textContent).toBe('');
      view.unmount();
    }
  });
});
