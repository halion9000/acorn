import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const summary = { total_techniques: 0, tested_techniques: 0, detected_techniques: 0, overall_coverage: 0 };
const answer = (url: string) => {
  if (url.includes('/coverage')) return { tactics: [], techniques: {}, summary };
  if (url.includes('/drift/latest')) return { current: null, previous: null, drift: { techniques: [], summary: { current: {}, previous: {}, delta: { delta_total: 0, delta_tested: 0, delta_detected: 0, delta_coverage: 0 }, regressed: 0, improved: 0, new: 0, removed: 0 } } };
  return [];
};
vi.mock('@/lib/auth-session', () => ({ authFetch: vi.fn(async (url: string) => new Response(JSON.stringify(answer(url)), { status: 200 })) }));

import PurpleTeamPage from './page';

describe('the Purple Team page', () => {
  it('says plainly what each tab does and that it does not run tests itself', async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <PurpleTeamPage />
      </SWRConfig>,
    );
    const help = await screen.findByTestId('purple-team-help');
    expect(help).toHaveTextContent('this page does not run anything on a machine');
    expect(help).toHaveTextContent('Tabletop');
    expect(help).toHaveTextContent('Coverage');
    expect(screen.getByRole('button', { name: 'Executions' })).toBeInTheDocument();
  });
});
