'use client';

/** What A.C.O.R.N keeps and for how long, in one table: the answer to a client's "how long do you keep my data", built from the live settings so it is always true. */

import useSWR from 'swr';
import { authFetch } from '@/lib/auth-session';

interface Line {
  what: string;
  kept: string;
  ends: string;
}

async function load(): Promise<Line[]> {
  const res = await authFetch('/api/v1/data-retention');
  if (!res.ok) throw new Error(`Could not load (${res.status})`);
  return res.json();
}

export function DataRetention() {
  const { data, error, isLoading } = useSWR<Line[]>('data-retention', load, { revalidateOnFocus: false });
  return (
    <div className="max-w-5xl space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Data retention</h1>
        <p className="mt-0.5 text-sm text-gray-500">What is kept, for how long, and what ends it. This follows the platform&apos;s live settings.</p>
      </div>
      {isLoading ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {error ? <p className="text-sm text-red-300">Could not load this page.</p> : null}
      {data ? (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Data</th>
                <th className="px-3 py-2">Kept</th>
                <th className="px-3 py-2">What ends it</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map((l) => (
                <tr key={l.what}>
                  <td className="px-3 py-2 text-gray-100">{l.what}</td>
                  <td className="px-3 py-2 text-gray-200">{l.kept}</td>
                  <td className="px-3 py-2 text-gray-400">{l.ends}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
