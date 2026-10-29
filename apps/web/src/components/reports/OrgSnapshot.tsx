'use client';

/**
 * The organization-wide part of the Executive Digest: how every client stands on the checks A.C.O.R.N runs from its tools, which clients stand worst, and which areas (backups, Windows support, renewals...)
 * have the most clients with a problem. Shown when no client is chosen; read from the Fleet Posture endpoints, so it says what that page says.
 */
import Link from 'next/link';
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';

export interface FleetClient {
  client_id: string;
  client_name: string | null;
  score: number | null;
  met: number;
  partly: number;
  not_met: number;
  below_target?: boolean;
}

export interface FleetSummary {
  average_score?: number | null;
  clients: FleetClient[];
}

export interface BoardRow {
  client_id: string;
  status: string;
  accepted?: boolean;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as T;
}

/** How many clients are scored, how many are under their own target, and the worst few (lowest score first, then the most checks not met). Clients with no score are left out of the ranking. */
export function orgSummary(fleet: FleetSummary, shown = 8): { scored: number; belowTarget: number; average: number | null; worst: FleetClient[] } {
  const scored = fleet.clients.filter((c) => c.score !== null);
  const worst = [...scored].sort((a, b) => (a.score as number) - (b.score as number) || b.not_met - a.not_met || (a.client_name ?? '').localeCompare(b.client_name ?? '')).slice(0, shown);
  return { scored: scored.length, belowTarget: fleet.clients.filter((c) => c.below_target).length, average: fleet.average_score ?? null, worst };
}

/** The clients with at least one check on a board that is not fine and not accepted by a person, once each. */
export function clientsWithProblems(rows: BoardRow[]): number {
  return new Set(rows.filter((r) => r.status !== 'met' && !r.accepted).map((r) => r.client_id)).size;
}

async function readBoards(): Promise<{ name: string; title: string; clients: number }[]> {
  const boards = await getJson<Record<string, { title: string }>>('/api/v1/client-posture/fleet/boards');
  const out = await Promise.all(
    Object.entries(boards).map(async ([name, b]) => {
      try {
        const rows = (await getJson<{ rows: BoardRow[] }>(`/api/v1/client-posture/fleet/boards/${encodeURIComponent(name)}`)).rows;
        return { name, title: b.title, clients: clientsWithProblems(rows) };
      } catch {
        return { name, title: b.title, clients: -1 };
      }
    }),
  );
  return out.filter((b) => b.clients >= 0).sort((a, b) => b.clients - a.clients);
}

export function OrgSnapshot() {
  const fleet = useSWR('org-fleet', () => getJson<FleetSummary>('/api/v1/client-posture/fleet/summary'), { revalidateOnFocus: false, shouldRetryOnError: false });
  const boards = useSWR('org-boards', readBoards, { revalidateOnFocus: false, shouldRetryOnError: false });
  // Nothing to say when the fleet cannot be read (the page may not be allowed to, or there are no clients).
  if (fleet.error || !fleet.data || fleet.data.clients.length === 0) return null;
  const s = orgSummary(fleet.data);
  return (
    <section className="rounded-xl border border-gray-700 bg-gray-900 p-5" aria-label="Across all clients" data-testid="org-snapshot">
      <h2 className="text-base font-semibold text-white">Across all clients</h2>
      <p className="mb-3 mt-0.5 text-xs text-gray-500">How every client stands on the checks run from the connected tools, as the Fleet Posture page shows them.</p>
      <p className="text-sm text-gray-200">
        {s.average !== null ? `Average check score ${s.average} across ${s.scored} clients` : `${s.scored} clients scored`}
        {s.belowTarget > 0 ? `; ${s.belowTarget} below the target set for them` : ''}.{' '}
        <Link href="/settings/fleet-posture" className="text-sky-300 underline hover:text-sky-200">
          Open Fleet Posture →
        </Link>
      </p>
      {s.worst.length > 0 && (
        <div className="mt-3">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Lowest scores</h3>
          <ul className="space-y-0.5 text-sm" data-testid="org-worst">
            {s.worst.map((c) => (
              <li key={c.client_id} className="text-gray-300">
                <Link href={`/settings/client-posture?client=${encodeURIComponent(c.client_id)}`} className="text-sky-300 hover:underline">
                  {c.client_name ?? 'This organization'}
                </Link>
                <span className="text-gray-500">
                  {' '}
                  · score {c.score} · {c.not_met} not met, {c.partly} partly
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {boards.data && boards.data.length > 0 && (
        <div className="mt-3">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Where the most clients have a problem</h3>
          <ul className="space-y-0.5 text-sm" data-testid="org-boards">
            {boards.data.map((b) => (
              <li key={b.name} className="text-gray-300">
                {b.title}: <span className={b.clients > 0 ? 'text-amber-300' : 'text-emerald-300'}>{b.clients} {b.clients === 1 ? 'client' : 'clients'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
