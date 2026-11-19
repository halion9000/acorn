'use client';

/**
 * Identities > Joiners and leavers: directory accounts A.C.O.R.N first saw in the last days, and accounts that were disabled or are no longer listed. The directory does not say when someone joined, so the join
 * day is the day A.C.O.R.N first saw the account (accounts already there when a source first reported are not shown as joiners), and leavers are recorded from that first report on.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

interface Row {
  client: string;
  upn: string;
  name: string;
  when: string;
}
export interface JoinersLeaversData {
  days: number;
  joiners: Row[];
  leavers: Row[];
  recorded_since: string | null;
}

function Table({ rows, label, testId }: { rows: Row[]; label: string; testId: string }) {
  if (rows.length === 0) return <p className="text-sm text-gray-400">None in this period.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm" data-testid={testId}>
        <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
          <tr>
            <th className="px-3 py-2 text-left">Client</th>
            <th className="px-3 py-2 text-left">Account</th>
            <th className="px-3 py-2 text-left">Name</th>
            <th className="px-3 py-2 text-left">{label}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800 text-gray-200">
          {rows.map((r) => (
            <tr key={`${r.client}|${r.upn}|${r.when}`}>
              <td className="px-3 py-1.5">{r.client}</td>
              <td className="px-3 py-1.5">{r.upn}</td>
              <td className="px-3 py-1.5">{r.name}</td>
              <td className="px-3 py-1.5">{r.when.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JoinersLeavers() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<JoinersLeaversData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/identity/joiners-leavers?days=${days}`);
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as JoinersLeaversData;
        if (live) {
          setData(body);
          setProblem(null);
        }
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, [days]);
  return (
    <section className="space-y-3 px-6 pb-8" data-testid="joiners-leavers">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-white">Joiners and leavers</h2>
        <label className="text-xs text-gray-400">
          Period{' '}
          <select className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 365].map((d) => (
              <option key={d} value={d}>{`Last ${d} days`}</option>
            ))}
          </select>
        </label>
      </div>
      {problem ? <p className="text-sm text-amber-300">{problem}</p> : null}
      {data ? (
        <>
          <p className="text-xs text-gray-500">
            The join day is the day A.C.O.R.N first saw the account; accounts already there when a directory first reported are not shown as joiners. {data.recorded_since ? `Recorded since ${data.recorded_since.slice(0, 10)}.` : 'Nothing is recorded yet.'}
          </p>
          <h3 className="text-sm font-semibold text-gray-200">Joined ({data.joiners.length})</h3>
          <Table rows={data.joiners} label="First seen" testId="joiners" />
          <h3 className="text-sm font-semibold text-gray-200">Left or disabled ({data.leavers.length})</h3>
          <Table rows={data.leavers} label="Left" testId="leavers" />
        </>
      ) : null}
    </section>
  );
}
