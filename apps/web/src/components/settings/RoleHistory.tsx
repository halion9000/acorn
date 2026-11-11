'use client';

import useSWR from 'swr';
import { authFetch } from '@/lib/auth-session';

export interface RoleChange {
  at: string | null;
  by: string | null;
  action: string;
  summary: string;
}

const fetchHistory = (url: string): Promise<RoleChange[]> =>
  authFetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

/** "2026-11-10 09:30" from an ISO time, or "" when there is none or it cannot be read. */
export function changeTime(at: string | null): string {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  return d.toISOString().slice(0, 16).replace('T', ' ');
}

/** The last ten changes to a role and to who holds it. Extra detail: while it loads, or if it cannot be read, nothing is shown and the editor is unaffected. */
export function RoleHistory({ roleId }: { roleId: string }) {
  const { data } = useSWR<RoleChange[]>(`/api/v1/rbac/roles/${roleId}/history`, fetchHistory, { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!data || data.length === 0) return null;
  return (
    <div data-testid="role-history">
      <h3 className="mb-1 text-sm font-medium text-gray-200">Recent changes to this role (times in UTC)</h3>
      <ul className="space-y-1 text-xs text-gray-300">
        {data.map((c, i) => (
          <li key={`${c.at}-${i}`}>
            <span className="text-gray-500">{changeTime(c.at)}</span> {c.by ? <span className="text-gray-400">{c.by}</span> : null} {c.summary}
          </li>
        ))}
      </ul>
    </div>
  );
}
