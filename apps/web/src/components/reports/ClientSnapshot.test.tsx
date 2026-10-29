import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import type { Review } from '@/app/(app)/reports/client-review/ClientReview';
import { ClientSnapshot, readinessThemes, snapshotLines } from './ClientSnapshot';

const review = (over: Partial<Review> = {}): Review =>
  ({
    client_id: 'c1',
    client_name: "Austin's Park",
    generated_at: '2026-10-29T12:00:00Z',
    window_days: 30,
    devices: {
      endpoints: 20,
      coverage: [
        { tool: 'huntress', have: 17, of: 20, percent: 85 },
        { tool: 'ninjaone', have: 20, of: 20, percent: 100 },
        { tool: 'dnsfilter', have: 0, of: 20, percent: 0, enrolled: false },
      ],
      stale_agents: 2,
      offline: 1,
      with_known_exploited: 0,
      with_ransomware_exploit: 0,
    },
    mfa: { people: 131, with_mfa: 75, not_required: 0, without_mfa: 7, admins_without_mfa: 2 },
    secure_score: { percent: 43.1, current: 115, max: 267, average: 54, taken_at: '2026-10-21T00:00:00Z' },
    alerts: { open: 6, critical_open: 0, high_open: 1, opened_30d: 8, closed_30d: 2 },
    cases: { open: 0, opened_30d: 0, resolved_30d: 0 },
    readiness: { met: 11, partly: 3, not_met: 14, unknown: 3, items: [] },
    ...over,
  }) as Review;

beforeEach(() => authFetch.mockReset());
afterEach(() => cleanup());

describe('snapshotLines', () => {
  it('says the devices, the tool gaps with a link to the missing ones, and leaves out a tool that is complete or not enrolled', () => {
    const lines = snapshotLines(review());
    const devices = lines.find((l) => l.label === 'Devices')!;
    expect(devices.text).toBe('20 computers, 2 with an agent not checking in, 1 offline.');
    const huntress = lines.find((l) => l.label.startsWith('Huntress'))!;
    expect(huntress.text).toBe('17 of 20 computers (85%); 3 missing.');
    expect(huntress.href).toBe('/devices?client=c1&missing=huntress');
    expect(lines.some((l) => l.label.startsWith('NinjaOne'))).toBe(false);
    expect(lines.find((l) => l.label.startsWith('DNSFilter'))!.text).toBe('Not currently enrolled for this client.');
  });

  it('names the people without Multi-Factor with a link, and says when none is known', () => {
    const mfa = snapshotLines(review()).find((l) => l.label === 'Multi-Factor')!;
    expect(mfa.text).toBe('75 of 131 people have a required second factor; 7 have none, 2 of them administrators.');
    expect(mfa.href).toBe('/settings/mfa?client=c1&which=without');
    expect(snapshotLines(review({ mfa: null })).find((l) => l.label === 'Multi-Factor')!.text).toBe('No Multi-Factor data has arrived for this client.');
  });

  it('says so for a client with no computers and no Secure Score instead of leaving them out', () => {
    const lines = snapshotLines(review({ secure_score: null, devices: { endpoints: 0, coverage: [], stale_agents: 0, offline: 0, with_known_exploited: null, with_ransomware_exploit: null } }));
    expect(lines.find((l) => l.label === 'Devices')!.text).toBe('No computers are listed for this client.');
    expect(lines.find((l) => l.label === 'Microsoft Secure Score')!.text).toBe('Not read for this client.');
  });
});

describe('ClientSnapshot', () => {
  const view = (id: string) =>
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
        <ClientSnapshot clientId={id} />
      </SWRConfig>,
    );

  it('shows nothing without a client', () => {
    view('');
    expect(screen.queryByTestId('client-snapshot')).toBeNull();
    expect(authFetch).not.toHaveBeenCalled();
  });

  it('reads the client and shows its lines', async () => {
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(review()) });
    view('c1');
    expect(await screen.findByText(/20 computers, 2 with an agent not checking in/)).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/client-review/c1');
    expect(screen.getByRole('link', { name: 'See the 3 missing →' })).toHaveAttribute('href', '/devices?client=c1&missing=huntress');
  });

  it('says why when the client could not be read', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({}) });
    view('c1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not read this client: The API answered 500');
  });
});

describe('readinessThemes', () => {
  const item = (key: string, status: 'met' | 'partly' | 'not_met' | 'unknown', evidence = '') => ({ key, question: `Question ${key}?`, status, evidence });
  it('groups the answers by area, counts the met ones of those that could be answered, and lists what is not met first', () => {
    const themes = readinessThemes([
      item('mailbox_backup_coverage', 'met'),
      item('backups_verified', 'partly', 'one system not test-booted.'),
      item('backup_appliance_current', 'not_met', 'two systems stale.'),
      item('backups', 'unknown'),
      item('mfa_everyone', 'not_met', '7 have none.'),
      item('ir_plan', 'not_met'),
    ]);
    expect(themes.map((t) => t.title)).toEqual(['Backups and recovery', 'Identity and sign-in']);
    const backups = themes[0];
    expect([backups.met, backups.known]).toEqual([1, 3]);
    expect(backups.problems.map((p) => p.key)).toEqual(['backup_appliance_current', 'backups_verified']);
    expect(themes[1].problems.map((p) => p.key)).toEqual(['mfa_everyone']);
  });
  it('has no area when none of its answers is known', () => {
    expect(readinessThemes([item('edr', 'unknown'), item('ir_plan', 'met')])).toEqual([]);
    expect(readinessThemes([])).toEqual([]);
  });
});

describe('the snapshot shows the areas', () => {
  it('lists each area with its problems and the links behind them', async () => {
    authFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve(
          review({
            readiness: {
              met: 0,
              partly: 0,
              not_met: 2,
              unknown: 0,
              items: [
                { key: 'edr', question: 'Is endpoint detection on every computer?', status: 'partly', evidence: '17 of 20.' },
                { key: 'backup_appliance_current', question: 'Does every system back up daily?', status: 'not_met', evidence: 'Two systems stale.' },
              ],
            },
          }),
        ),
    });
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
        <ClientSnapshot clientId="c1" />
      </SWRConfig>,
    );
    const themes = await screen.findByTestId('snapshot-themes');
    expect(themes).toHaveTextContent('Backups and recovery: 0 of 1 met');
    expect(themes).toHaveTextContent('Not met · Does every system back up daily? Two systems stale.');
    expect(themes).toHaveTextContent('Computers: patching and protection: 0 of 1 met');
    expect(screen.getAllByRole('link', { name: 'See the computers missing Huntress →' }).some((a) => a.getAttribute('href') === '/devices?client=c1&missing=huntress')).toBe(true);
  });
});
