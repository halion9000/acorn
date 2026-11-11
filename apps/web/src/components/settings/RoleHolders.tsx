'use client';

import useSWR from 'swr';
import { authFetch } from '@/lib/auth-session';

export interface RoleHolder {
  user_id: string;
  name: string;
  email: string | null;
  since: string | null;
  active: boolean;
}

const fetchHolders = (url: string): Promise<RoleHolder[]> =>
  authFetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

/** "since 2026-11-10" from an ISO time, or "" when there is none or it cannot be read (pure). */
export function sinceLabel(since: string | null): string {
  if (!since) return '';
  const d = new Date(since);
  return Number.isNaN(d.getTime()) ? '' : `since ${d.toISOString().slice(0, 10)}`;
}

/** "Held by 3 people" / "Held by 1 person" / "Nobody holds this role" (pure). */
export function holdersHeading(count: number): string {
  if (count === 0) return 'Nobody holds this role';
  return `Held by ${count} ${count === 1 ? 'person' : 'people'}`;
}

/** Who holds the role now, the longest holder first. Extra detail: while it loads, or if it cannot be read, nothing is shown and the editor is unaffected. */
export function RoleHolders({ roleId }: { roleId: string }) {
  const { data } = useSWR<RoleHolder[]>(`/api/v1/rbac/roles/${roleId}/holders`, fetchHolders, { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!Array.isArray(data)) return null;
  return (
    <div data-testid="role-holders">
      <h3 className="mb-1 text-sm font-medium text-gray-200">{holdersHeading(data.length)}</h3>
      {data.length > 0 ? (
        <ul className="space-y-1 text-xs text-gray-300">
          {data.map((h) => (
            <li key={h.user_id} data-testid="role-holder">
              {h.name}
              {h.email && h.email !== h.name ? <span className="text-gray-400"> ({h.email})</span> : null} <span className="text-gray-500">{sinceLabel(h.since)}</span>
              {h.active ? null : <span className="text-amber-300"> · account turned off</span>}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
