'use client';

/**
 * Reports > Device Versions: two lists worked out from what the tools already tell A.C.O.R.N about each device. Huntress agents: the spread of versions across the clients and the agents more than two releases behind the newest the
 * fleet runs. Network devices (Auvik): devices running older firmware than another device of the same make and model. "Newest" is the newest the fleet itself runs; there is no list of the vendors' releases.
 */
import { useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from '@/components/finance/SortHeader';

export interface HuntressReport {
  newest: string | null;
  agents: number;
  without_version: number;
  spread: { version: string; agents: number; releases_behind: number }[];
  old: { client: string; hostname: string; version: string; releases_behind: number; last_callback: string | null }[];
}
export interface FirmwareReport {
  models: { manufacturer: string; model: string; newest: string; devices: number; behind: number; versions: string[] }[];
  devices: { client: string; hostname: string; manufacturer: string; model: string; device_type: string; firmware: string; newest: string }[];
}

export interface OfflineReport {
  vendor: string;
  days: number;
  offline_now: number;
  devices: { client: string; hostname: string; model: string; offline_since: string; days_offline: number }[];
}

/** How far behind an agent is, in words (pure). */
export function behindText(n: number): string {
  return n === 0 ? 'Current' : n === 1 ? '1 release behind' : `${n} releases behind`;
}

function useRead<T>(url: string): { data: T | null; problem: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch(url);
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        if (live) setData((await res.json()) as T);
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, [url]);
  return { data, problem };
}

const th = 'px-3 py-2 text-left';
const td = 'px-3 py-1.5 text-left';

function Sorted<T extends object>({ rows, cols, testId }: { rows: T[]; cols: { label: string; field: keyof T & string; numeric?: boolean }[]; testId: string }) {
  const [sort, setSort] = useState<SortState | null>(null);
  const shown = useMemo(() => (sort ? sortedBy(rows, (r) => (r as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : rows), [rows, sort]);
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm" data-testid={testId}>
        <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
          <tr>
            {cols.map((c) => (
              <SortHeader key={c.field} label={c.label} field={c.field} sort={sort} onSort={setSort} text={!c.numeric} className={th} />
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800 text-gray-200">
          {shown.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c.field} className={td}>
                  {String((r as Record<string, unknown>)[c.field] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DeviceVersions() {
  const h = useRead<HuntressReport>('/api/v1/device-reports/huntress-versions');
  const f = useRead<FirmwareReport>('/api/v1/device-reports/network-firmware');
  const o = useRead<OfflineReport>('/api/v1/device-reports/offline');
  return (
    <div className="space-y-8 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Device versions</h1>
        <p className="mt-1 text-sm text-gray-400">What the tools report for each device, compared across all clients. &quot;Newest&quot; is the newest version the fleet itself runs, since there is no list of the vendors&apos; releases.</p>
      </div>

      <section className="space-y-3" data-testid="huntress-versions">
        <h2 className="text-lg font-semibold text-white">Huntress agents</h2>
        {h.problem ? <p className="text-sm text-amber-300">{h.problem}</p> : null}
        {h.data ? (
          h.data.agents === 0 ? (
            <p className="text-sm text-gray-400">No Huntress agent has reported a version yet.</p>
          ) : (
            <>
              <p className="text-sm text-gray-300">
                {h.data.agents} agents; newest version <span className="font-mono">{h.data.newest}</span>; {h.data.old.length} more than two releases behind{h.data.without_version > 0 ? `; ${h.data.without_version} with no version reported` : ''}.
              </p>
              <Sorted rows={h.data.spread.map((s) => ({ ...s, behind: behindText(s.releases_behind) }))} cols={[{ label: 'Version', field: 'version' }, { label: 'Agents', field: 'agents', numeric: true }, { label: 'Behind', field: 'releases_behind', numeric: true }]} testId="huntress-spread" />
              {h.data.old.length > 0 ? (
                <>
                  <h3 className="text-sm font-semibold text-gray-200">More than two releases behind</h3>
                  <Sorted rows={h.data.old} cols={[{ label: 'Client', field: 'client' }, { label: 'Machine', field: 'hostname' }, { label: 'Version', field: 'version' }, { label: 'Releases behind', field: 'releases_behind', numeric: true }, { label: 'Last check-in', field: 'last_callback' }]} testId="huntress-old" />
                </>
              ) : null}
            </>
          )
        ) : null}
      </section>

      <section className="space-y-3" data-testid="network-firmware">
        <h2 className="text-lg font-semibold text-white">Network device firmware (Auvik)</h2>
        {f.problem ? <p className="text-sm text-amber-300">{f.problem}</p> : null}
        {f.data ? (
          f.data.devices.length === 0 ? (
            <p className="text-sm text-gray-400">No device runs older firmware than another of the same make and model.</p>
          ) : (
            <>
              <Sorted rows={f.data.models.map((m) => ({ ...m, versions: m.versions.join(', ') }))} cols={[{ label: 'Make', field: 'manufacturer' }, { label: 'Model', field: 'model' }, { label: 'Newest', field: 'newest' }, { label: 'Devices', field: 'devices', numeric: true }, { label: 'Behind', field: 'behind', numeric: true }, { label: 'Versions seen', field: 'versions' }]} testId="firmware-models" />
              <h3 className="text-sm font-semibold text-gray-200">Devices behind</h3>
              <Sorted rows={f.data.devices} cols={[{ label: 'Client', field: 'client' }, { label: 'Device', field: 'hostname' }, { label: 'Type', field: 'device_type' }, { label: 'Make', field: 'manufacturer' }, { label: 'Model', field: 'model' }, { label: 'Firmware', field: 'firmware' }, { label: 'Newest', field: 'newest' }]} testId="firmware-devices" />
            </>
          )
        ) : null}
      </section>

      <section className="space-y-3" data-testid="unifi-offline">
        <h2 className="text-lg font-semibold text-white">UniFi devices offline for more than a week</h2>
        {o.problem ? <p className="text-sm text-amber-300">{o.problem}</p> : null}
        {o.data ? (
          <>
            <p className="text-sm text-gray-400">UniFi says whether a device is offline but not since when, so the count starts the day A.C.O.R.N first saw it offline. {o.data.offline_now} offline now.</p>
            {o.data.devices.length === 0 ? (
              <p className="text-sm text-gray-400">No UniFi device has been offline for more than a week.</p>
            ) : (
              <Sorted rows={o.data.devices} cols={[{ label: 'Client', field: 'client' }, { label: 'Device', field: 'hostname' }, { label: 'Model', field: 'model' }, { label: 'Offline since', field: 'offline_since' }, { label: 'Days offline', field: 'days_offline', numeric: true }]} testId="unifi-offline-table" />
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}
