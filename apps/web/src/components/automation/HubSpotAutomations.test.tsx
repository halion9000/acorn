import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { HubSpotAutomations, passSummary } from './HubSpotAutomations';

const run = (over: Record<string, unknown> = {}) => ({
  source: 'halo-hubspot',
  title: 'Halo tickets to HubSpot',
  ran_at: '2026-11-16T12:10:00Z',
  accounts: 12,
  sent: 3,
  failed: 0,
  waiting: 0,
  skipped: 9,
  first_error: '',
  health: 'ok',
  ...over,
});
const answer = (rows: unknown[], status = 200) => Promise.resolve(new Response(JSON.stringify(rows), { status, headers: { 'content-type': 'application/json' } }));

beforeEach(() => {
  authFetch.mockReset();
});

describe('passSummary', () => {
  it('says what the last pass did in words, mentioning companies and problems only when there were some', () => {
    expect(passSummary(run() as never)).toEqual(['12 Halo tickets in the category', '3 copied or moved to another stage', '9 already in step, or opened before it was switched on']);
    expect(passSummary(run({ accounts: 1, waiting: 2, failed: 1 }) as never)).toEqual([
      '1 Halo ticket in the category',
      '3 copied or moved to another stage',
      '9 already in step, or opened before it was switched on',
      "2 tickets created without a company (no single HubSpot company has the client's name)",
      '1 problem',
    ]);
  });
});

describe('HubSpotAutomations', () => {
  it('shows the automation as running with what the last pass did, from the halo-hubspot sweep and no other', async () => {
    authFetch.mockReturnValue(answer([run({ source: 'person-tickets', accounts: 999 }), run()]));
    render(<HubSpotAutomations />);
    const last = await screen.findByTestId('halo-hubspot-last');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/client-posture/sweeps/latest');
    expect(last).toHaveTextContent('Last checked 2026-11-16 12:10');
    expect(last).toHaveTextContent('12 Halo tickets in the category');
    expect(last).not.toHaveTextContent('999');
    expect(screen.getByTestId('halo-hubspot-card')).toHaveTextContent('Running');
    expect(screen.queryByTestId('halo-hubspot-off')).toBeNull();
  });

  it('says how to turn it on when CORE has not reported it', async () => {
    authFetch.mockReturnValue(answer([run({ source: 'person-tickets' })]));
    render(<HubSpotAutomations />);
    const off = await screen.findByTestId('halo-hubspot-off');
    expect(off).toHaveTextContent('Connectors, then HubSpot');
    expect(off).toHaveTextContent('Copy Halo tickets to HubSpot');
    expect(screen.getByTestId('halo-hubspot-card')).toHaveTextContent('Not running');
  });

  it('shows a failing pass with the error and who to look at, and a stale one as not run for 48 hours', async () => {
    authFetch.mockReturnValue(answer([run({ health: 'failed', failed: 1, sent: 0, first_error: 'HubSpot refused the access token (it is wrong, revoked or expired)' })]));
    const a = render(<HubSpotAutomations />);
    const err = await screen.findByTestId('halo-hubspot-error');
    expect(err).toHaveTextContent('HubSpot refused the access token');
    expect(err).toHaveTextContent('the tool refused the key');
    expect(screen.getByTestId('halo-hubspot-card')).toHaveTextContent('Failing');
    a.unmount();
    authFetch.mockReturnValue(answer([run({ health: 'stale' })]));
    render(<HubSpotAutomations />);
    await waitFor(() => expect(screen.getByTestId('halo-hubspot-card')).toHaveTextContent('Has not run for 48 hours'));
  });

  it('says so when the status cannot be read, and still explains the automation', async () => {
    authFetch.mockReturnValue(answer([], 500));
    render(<HubSpotAutomations />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The sweep list answered 500');
    expect(screen.getByTestId('halo-hubspot-card')).toHaveTextContent('HaloPSA tickets to HubSpot');
  });
});

describe('Sync now', () => {
  it('asks for a sync, says CORE collects it within about 15 seconds, and looks at the status again by itself', async () => {
    let calls = 0;
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/v1/automation/hubspot/sync') return Promise.resolve(new Response('{}', { status: 202 }));
      calls++;
      return answer([run({ accounts: calls === 1 ? 0 : 5 })]);
    });
    render(<HubSpotAutomations refreshAfterSyncMs={[10, 20]} />);
    await screen.findByTestId('halo-hubspot-last');
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/automation/hubspot/sync', { method: 'POST' });
    expect(await screen.findByTestId('sync-note')).toHaveTextContent('about 15 seconds');
    await waitFor(() => expect(screen.getByTestId('halo-hubspot-last')).toHaveTextContent('5 Halo tickets in the category'));
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it('says plainly when the request is refused, and does not look again', async () => {
    authFetch.mockImplementation((url: string) => (url === '/api/v1/automation/hubspot/sync' ? Promise.resolve(new Response('{}', { status: 403 })) : answer([run()])));
    render(<HubSpotAutomations refreshAfterSyncMs={[10]} />);
    await screen.findByTestId('halo-hubspot-last');
    const before = authFetch.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(await screen.findByTestId('sync-note')).toHaveTextContent('You can read this but not ask for a sync.');
    await new Promise((r) => setTimeout(r, 40));
    expect(authFetch.mock.calls.length).toBe(before + 1);
  });

  it('shows the reason CORE gives when it cannot run the copy, as the status of the last pass', async () => {
    authFetch.mockReturnValue(answer([run({ health: 'failed', failed: 1, accounts: 0, sent: 0, skipped: 0, first_error: "Not run: it is not set up in CORE's HubSpot connector yet (needs the switch Copy Halo tickets to HubSpot)." })]));
    render(<HubSpotAutomations />);
    expect(await screen.findByTestId('halo-hubspot-error')).toHaveTextContent('needs the switch Copy Halo tickets to HubSpot');
  });
});
