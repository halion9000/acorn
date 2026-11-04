'use client';

/** How far each client has got from "added" to "everything is flowing": five steps read from what is really there, least onboarded first, each with the one next thing to do. */

import { useState } from 'react';
import useSWR from 'swr';
import { authFetch } from '@/lib/auth-session';

interface Step {
  key: string;
  label: string;
  done: boolean;
  detail: string;
}
interface Row {
  client_id: string;
  client_name: string;
  steps: Step[];
  done: number;
  total: number;
  percent: number;
  next_step: string | null;
  first_data_at: string | null;
}

async function load(): Promise<Row[]> {
  const res = await authFetch('/api/v1/client-onboarding');
  if (!res.ok) throw new Error(`Could not load (${res.status})`);
  return res.json();
}

/** The table as a CSV file: asks the server for the same rows and hands them to the browser as a download. Throws with a short reason when it cannot. */
export async function downloadOnboardingCsv(): Promise<void> {
  const res = await authFetch('/api/v1/client-onboarding/export.csv');
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const url = URL.createObjectURL(new Blob([await res.text()], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'client-onboarding.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export function ClientOnboarding() {
  const [exportError, setExportError] = useState<string | null>(null);
  const { data, error, isLoading } = useSWR<Row[]>('client-onboarding', load, { revalidateOnFocus: false });
  const unfinished = (data ?? []).filter((r) => r.done < r.total).length;
  return (
    <div className="max-w-6xl space-y-4 p-6">
      <div>
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-xl font-semibold text-gray-100">Client onboarding</h1>
          <button
            type="button"
            onClick={() => {
              setExportError(null);
              downloadOnboardingCsv().catch((err: unknown) => setExportError(err instanceof Error ? err.message : 'Could not export.'));
            }}
            className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white hover:bg-gray-800"
          >
            Export CSV
          </button>
        </div>
        {exportError ? <p role="alert" className="text-sm text-red-300">{exportError}</p> : null}
        <p className="mt-0.5 text-sm text-gray-500">
          Five steps per client, each counted from what is really there. {data ? `${unfinished} of ${data.length} clients still have a step to do.` : ''}
        </p>
      </div>
      {isLoading ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {error ? <p className="text-sm text-red-300">Could not load this page.</p> : null}
      {data ? (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Client</th>
                {(data[0]?.steps ?? []).map((s) => (
                  <th key={s.key} className="px-3 py-2">
                    {s.label}
                  </th>
                ))}
                <th className="px-3 py-2">Next</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map((r) => (
                <tr key={r.client_id} data-testid="onboarding-row">
                  <td className="whitespace-nowrap px-3 py-2 text-gray-100">
                    {r.client_name} <span className="text-xs text-gray-500">{r.percent}%</span>
                  </td>
                  {r.steps.map((s) => (
                    <td key={s.key} className={`whitespace-nowrap px-3 py-2 text-xs ${s.done ? 'text-emerald-300' : 'text-amber-300'}`} title={s.detail}>
                      {s.done ? 'Done' : 'To do'}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-xs text-gray-400">{r.next_step ?? 'Nothing: all five are in place.'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
