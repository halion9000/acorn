'use client';

/**
 * Device lifecycle: every computer with how long A.C.O.R.N has known it and whether its operating system is still patched, worst first. There is no purchase date in any tool, so age counts from the day the
 * machine was first seen (a floor, and said so); the operating-system column is the more reliable signal. A client can be picked to narrow it.
 */
import { useEffect, useState } from 'react';

import { ClientPicker } from '@/components/mssp/ClientPicker';
import { authFetch } from '@/lib/auth-session';

export interface LifecycleRow {
  device_id: string;
  client_name: string | null;
  hostname: string;
  os: string | null;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  first_seen: string;
  age_days: number;
  band: 'under_1' | '1_to_3' | '3_to_5' | 'over_5';
  os_support: 'ended' | 'supported' | 'unknown';
  review: boolean;
}
interface Lifecycle {
  basis: string;
  summary: { computers: number; bands: Record<string, number>; os_ended: number; os_unknown: number; review: number };
  rows: LifecycleRow[];
}

export const BAND_LABELS: Record<string, string> = { under_1: 'Under 1 year', '1_to_3': '1 to 3 years', '3_to_5': '3 to 5 years', over_5: 'Over 5 years' };
export const ageText = (days: number): string => (days >= 730 ? `${(days / 365.25).toFixed(1)} years` : days >= 60 ? `${Math.round(days / 30.4)} months` : `${days} days`);

const SUPPORT: Record<LifecycleRow['os_support'], { text: string; tone: string }> = {
  ended: { text: 'Ended', tone: 'text-red-300' },
  supported: { text: 'Supported', tone: 'text-emerald-300' },
  unknown: { text: 'Not known', tone: 'text-gray-500' },
};

export function DeviceLifecycleView() {
  const [client, setClient] = useState('');
  const [data, setData] = useState<Lifecycle | null>(null);
  const [problem, setProblem] = useState('');
  const [onlyReview, setOnlyReview] = useState(false);
  useEffect(() => {
    let live = true;
    setData(null);
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/devices/lifecycle${client ? `?client_id=${encodeURIComponent(client)}` : ''}`);
        if (!res.ok) throw new Error(res.status === 403 ? 'Reading devices needs the alerts permission.' : `The API answered ${res.status}`);
        const body = (await res.json()) as Lifecycle;
        if (live) {
          setData(body);
          setProblem('');
        }
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, [client]);

  const rows = (data?.rows ?? []).filter((r) => !onlyReview || r.review);
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Device lifecycle</h1>
          <a href="/devices" className="text-xs text-blue-300 hover:underline">
            Devices
          </a>
          <p className="mt-1 max-w-3xl text-sm text-gray-400">
            Computers, worst first: an operating system its maker no longer patches, then the oldest. There is no purchase date in any tool, so age counts from the day A.C.O.R.N <strong>first saw</strong> the machine: a machine already there
            when a tool was connected is at least that old.
          </p>
        </div>
        <ClientPicker value={client} onChange={setClient} ownLabel="All clients" label="Client" />
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6" data-testid="lifecycle-summary">
            <Card label="Computers" value={data.summary.computers} />
            {Object.entries(BAND_LABELS).map(([k, label]) => (
              <Card key={k} label={label} value={data.summary.bands[k] ?? 0} />
            ))}
            <Card label="Operating system ended" value={data.summary.os_ended} tone="text-red-300" />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} />
            Only machines worth a replacement review ({data.summary.review}): operating system ended, or first seen over 5 years ago
          </label>
          {rows.length === 0 ? (
            <p className="text-sm text-gray-400" data-testid="lifecycle-empty">
              No computers match.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-left text-sm" data-testid="lifecycle-table">
                <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-3 py-2">Client</th>
                    <th className="px-3 py-2">Device</th>
                    <th className="px-3 py-2">Operating system</th>
                    <th className="px-3 py-2">OS support</th>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">First seen</th>
                    <th className="px-3 py-2">Known for</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 text-gray-200">
                  {rows.map((r) => (
                    <tr key={r.device_id} data-testid="lifecycle-row">
                      <td className="px-3 py-1.5">{r.client_name ?? ''}</td>
                      <td className="px-3 py-1.5">
                        <a className="hover:underline" href={`/devices?search=${encodeURIComponent(r.hostname)}`}>
                          {r.hostname}
                        </a>
                      </td>
                      <td className="px-3 py-1.5">{r.os ?? ''}</td>
                      <td className={`px-3 py-1.5 ${SUPPORT[r.os_support].tone}`}>{SUPPORT[r.os_support].text}</td>
                      <td className="px-3 py-1.5 text-gray-400">{[r.manufacturer, r.model].filter(Boolean).join(' ')}</td>
                      <td className="px-3 py-1.5 whitespace-nowrap text-gray-400">{r.first_seen.slice(0, 10)}</td>
                      <td className="px-3 py-1.5 whitespace-nowrap">{ageText(r.age_days)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Card({ label, value, tone = 'text-white' }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}
