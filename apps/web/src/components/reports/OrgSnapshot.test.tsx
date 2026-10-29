import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { OrgSnapshot, clientsWithProblems, orgSummary, type FleetSummary } from './OrgSnapshot';

const client = (id: string, name: string, score: number | null, over: Record<string, unknown> = {}) => ({ client_id: id, client_name: name, score, met: 5, partly: 1, not_met: 2, ...over });
const FLEET: FleetSummary = { average_score: 71, clients: [client('a', 'Acme', 90), client('b', 'Birch', 40, { not_met: 9 }), client('c', 'Cedar', 40, { not_met: 12, below_target: true }), client('d', 'No score', null)] };
const json = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
const refused = (status: number) => Promise.resolve({ ok: false, status, json: () => Promise.resolve({}) });

/** Answers each address the component asks for; anything else is an empty object. */
function answer(routes: Record<string, () => Promise<unknown>>) {
  authFetch.mockImplementation((url?: string) => {
    const path = String(url ?? '');
    const key = Object.keys(routes).find((k) => path.endsWith(k));
    return key ? routes[key]() : json({});
  });
}

beforeEach(() => {
  authFetch.mockReset();
});
afterEach(() => cleanup());

describe('orgSummary', () => {
  it('ranks the lowest scores first, ties by the most checks not met, and leaves unscored clients out', () => {
    const s = orgSummary(FLEET);
    expect(s.worst.map((c) => c.client_name)).toEqual(['Cedar', 'Birch', 'Acme']);
    expect([s.scored, s.belowTarget, s.average]).toEqual([3, 1, 71]);
    expect(orgSummary(FLEET, 1).worst).toHaveLength(1);
  });
});

describe('clientsWithProblems', () => {
  it('counts each client once, and not one whose problem a person accepted or whose check is met', () => {
    expect(
      clientsWithProblems([
        { client_id: 'a', status: 'not_met' },
        { client_id: 'a', status: 'partly' },
        { client_id: 'b', status: 'met' },
        { client_id: 'c', status: 'not_met', accepted: true },
        { client_id: 'd', status: 'partly' },
      ]),
    ).toBe(2);
    expect(clientsWithProblems([])).toBe(0);
  });
});

describe('OrgSnapshot', () => {
  const view = () =>
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
        <OrgSnapshot />
      </SWRConfig>,
    );

  it('shows the average, the lowest-scoring clients with a link to each, and the areas ranked by clients with a problem', async () => {
    answer({
      '/fleet/summary': () => json(FLEET),
      '/fleet/boards': () => json({ backups: { title: 'Backups' }, windows: { title: 'Windows support and updates' } }),
      '/fleet/boards/backups': () => json({ rows: [{ client_id: 'a', status: 'not_met' }] }),
      '/fleet/boards/windows': () => json({ rows: [{ client_id: 'a', status: 'not_met' }, { client_id: 'b', status: 'partly' }] }),
    });
    view();
    const card = await screen.findByTestId('org-snapshot');
    expect(card).toHaveTextContent('Average check score 71 across 3 clients; 1 below the target set for them.');
    expect(screen.getByRole('link', { name: 'Cedar' })).toHaveAttribute('href', '/settings/client-posture?client=c');
    expect(screen.getByTestId('org-worst')).toHaveTextContent('score 40 · 12 not met, 1 partly');
    await waitFor(() => expect(screen.getByTestId('org-boards')).toBeInTheDocument());
    const items = screen.getByTestId('org-boards').querySelectorAll('li');
    expect(items[0]).toHaveTextContent('Windows support and updates: 2 clients');
    expect(items[1]).toHaveTextContent('Backups: 1 client');
  });

  it('shows nothing when the fleet cannot be read', async () => {
    answer({ '/fleet/summary': () => refused(403) });
    view();
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('org-snapshot')).toBeNull();
  });

  it('shows nothing when there are no clients', async () => {
    answer({ '/fleet/summary': () => json({ clients: [] }) });
    view();
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('org-snapshot')).toBeNull();
  });

  it('leaves out a board that could not be read', async () => {
    answer({
      '/fleet/summary': () => json(FLEET),
      '/fleet/boards': () => json({ backups: { title: 'Backups' }, windows: { title: 'Windows' } }),
      '/fleet/boards/backups': () => refused(500),
      '/fleet/boards/windows': () => json({ rows: [{ client_id: 'a', status: 'not_met' }] }),
    });
    view();
    await waitFor(() => expect(screen.getByTestId('org-boards')).toBeInTheDocument());
    expect(screen.getByTestId('org-boards')).toHaveTextContent('Windows: 1 client');
    expect(screen.getByTestId('org-boards')).not.toHaveTextContent('Backups');
  });
});
