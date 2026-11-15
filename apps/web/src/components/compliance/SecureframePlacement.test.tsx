import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/saveFile', () => ({ saveText: vi.fn() }));
vi.mock('@/lib/api', () => ({
  downloadCsv: vi.fn(),
  apiErrorDetail: () => null,
  msspApi: { listChildren: async () => [] },
  controlsApi: { list: async () => ({ enabled: [], frameworks: [], counts: { healthy: 0, at_risk: 0, unhealthy: 0, not_tested: 0 }, total: 0, rows: [] }) },
  riskRegisterApi: { list: async () => ({ risks: [], categories: [], summary: { total: 0, by_level: { critical: 0, high: 0, medium: 0, low: 0 }, matrix: [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]], open_tasks: 0, overdue_tasks: 0, untreated: 0 } }), library: async () => [] },
  complianceDashboardApi: { enabled: async () => ({ enabled: [], available: [] }) },
}));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock('./GovernancePanel', () => ({ GovernancePanel: () => <div data-testid="governance-panel" /> }));

import CompliancePoliciesPage from '../../app/(app)/compliance/policies/page';
import { ControlsView } from './ControlsView';
import { FrameworkIndex } from './FrameworkIndex';
import { RiskRegisterView } from './RiskRegisterView';

const REPORT = {
  report: {
    tests: { total: 7, enabled: 7, passing: 5, failing: 2, not_evaluated: 0, disabled: 0 },
    frameworks: [],
    failing: [],
    risks: 1,
    policies: 1,
    policy_list: [{ name: 'Access Control Policy', status: 'published', published_at: '2026-05-01T00:00:00Z', accepted: 4, eligible: 10 }],
    risk_list: [{ id: 'R-1', description: 'A laptop with client data is lost.', status: 'in_progress', treatment: 'mitigate', impact: 4, likelihood: 3 }],
  },
  received_at: null,
  passing_percent: 71,
};
const wrap = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(String(url).includes('/secureframe') ? REPORT : []) }));
  window.history.replaceState(null, '', '/compliance');
});
afterEach(() => cleanup());

describe('Secureframe pieces sit on their own pages, not on Frameworks', () => {
  it('the control tests are on Controls', async () => {
    wrap(<ControlsView />);
    expect(await screen.findByTestId('secureframe-card')).toBeTruthy();
  });

  it('the risk register is on Risk Management, without the policies', async () => {
    wrap(<RiskRegisterView />);
    expect(await screen.findByTestId('risks-summary')).toBeTruthy();
    expect(screen.queryByTestId('policies-summary')).toBeNull();
  });

  it('the policies are on Policies, without the risks', async () => {
    wrap(<CompliancePoliciesPage />);
    expect(await screen.findByTestId('policies-summary')).toBeTruthy();
    expect(screen.queryByTestId('risks-summary')).toBeNull();
    expect(screen.getByTestId('governance-panel')).toBeTruthy();
  });

  it('Frameworks shows only the frameworks: no control tests, policies, risks or risk register link', async () => {
    wrap(<FrameworkIndex frameworks={[{ id: 'soc2', name: 'SOC 2 Type II', badge: 'SOC 2', description: 'x' } as never]} />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('secureframe-card')).toBeNull();
    expect(screen.queryByTestId('secureframe-registers')).toBeNull();
    expect(screen.queryByRole('link', { name: /Risk register/ })).toBeNull();
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/api/v1/secureframe'))).toBe(false);
  });
});
