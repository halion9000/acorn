'use client';

/**
 * Remote tools: every remote management and remote access tool found on client devices (AnyDesk, TeamViewer, ScreenConnect, NinjaOne, Splashtop...), how many clients and devices each is on, and what
 * has been decided about it: allowed (we run it, or the client does on purpose), blocked (nobody should) or unreviewed. A blocked tool found on a device raises an alert.
 * Backed by GET /api/v1/remote-tools/inventory, GET .../tools/{key}/devices and PUT .../tools/{key}/verdict.
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { authFetch } from '@/lib/auth-session';

export type Verdict = 'allowed' | 'blocked' | 'unreviewed';

export interface ToolRow {
  key: string;
  name: string;
  category: string;
  clients: number;
  devices: number;
  last_seen: string | null;
  verdict: Verdict;
  client_rules: number;
  blocked_devices: number;
  allowed_devices: number;
  unreviewed_devices: number;
}

export interface Inventory {
  tools_found: number;
  devices_with_tools: number;
  devices_scanned: number;
  blocked_devices: number;
  last_scanned: string | null;
  tools: ToolRow[];
}

interface DeviceRow {
  client_id: string;
  client_name: string | null;
  hostname: string;
  version: string | null;
  last_seen: string;
  verdict: Verdict;
}

export type Filter = 'all' | Verdict;

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'unreviewed', label: 'Unreviewed' },
  { value: 'allowed', label: 'Approved' },
  { value: 'blocked', label: 'Blocked' },
];

const CATEGORY_LABELS: Record<string, string> = {
  rmm: 'Remote monitoring',
  remote_access: 'Remote access',
  remote_support: 'Remote support',
  file_transfer: 'File transfer',
  remote_desktop_manager: 'Connection manager',
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

/** The tools to list for a filter, by the decision for every client. */
export function filterTools(tools: ToolRow[], filter: Filter): ToolRow[] {
  return filter === 'all' ? tools : tools.filter((t) => t.verdict === filter);
}

export function counts(tools: ToolRow[]): Record<Filter, number> {
  return {
    all: tools.length,
    unreviewed: tools.filter((t) => t.verdict === 'unreviewed').length,
    allowed: tools.filter((t) => t.verdict === 'allowed').length,
    blocked: tools.filter((t) => t.verdict === 'blocked').length,
  };
}

/** "3,581 of 3,678": how many of the scanned devices carry one of these tools. */
export function reach(withTools: number, scanned: number): string {
  if (scanned <= 0) return `${withTools.toLocaleString()} (no devices scanned yet)`;
  return `${withTools.toLocaleString()} of ${scanned.toLocaleString()}`;
}

const BADGE: Record<Verdict, string> = {
  allowed: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  blocked: 'border-red-500/40 bg-red-500/10 text-red-300',
  unreviewed: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
};
const VERDICT_TEXT: Record<Verdict, string> = { allowed: 'Approved', blocked: 'Blocked', unreviewed: 'Unreviewed' };

function Badge({ verdict }: { verdict: Verdict }) {
  return <span className={`rounded border px-1.5 py-0.5 text-xs ${BADGE[verdict]}`}>{VERDICT_TEXT[verdict]}</span>;
}

function when(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

export default function RemoteToolsView() {
  const [data, setData] = useState<Inventory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<string | null>(null);
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/remote-tools/inventory');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setData((await res.json()) as Inventory);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the remote tools');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadDevices = useCallback(async (key: string) => {
    setDevices(null);
    try {
      const res = await authFetch(`/api/v1/remote-tools/tools/${encodeURIComponent(key)}/devices`);
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setDevices((await res.json()) as DeviceRow[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the devices');
    }
  }, []);

  const toggle = (key: string) => {
    if (open === key) {
      setOpen(null);
      return;
    }
    setOpen(key);
    void loadDevices(key);
  };

  const decide = async (tool: ToolRow, verdict: Verdict, client?: { id: string; name: string | null }) => {
    const where = client ? `for ${client.name ?? 'this client'}` : 'for every client';
    if (verdict === 'blocked' && !window.confirm(`Block ${tool.name} ${where}? Every device it is found on raises an alert.`)) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const res = await authFetch(`/api/v1/remote-tools/tools/${encodeURIComponent(tool.key)}/verdict`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ verdict, client_id: client?.id ?? null }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(res.status === 403 ? 'You need permission to manage clients to decide this.' : (body?.detail ?? `The API answered ${res.status}`));
      }
      const out = (await res.json()) as { alerts_raised: number };
      setNotice(`${tool.name} is now ${VERDICT_TEXT[verdict].toLowerCase()} ${where}.${out.alerts_raised > 0 ? ` ${out.alerts_raised} alert${out.alerts_raised === 1 ? '' : 's'} raised.` : ''}`);
      await load();
      if (open === tool.key) await loadDevices(tool.key);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  const tools = data ? filterTools(data.tools, filter) : [];
  const chip = data ? counts(data.tools) : null;

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Remote tools</h1>
        <p className="mt-1 text-sm text-gray-400">
          Remote management and remote access software found on client devices. Approve what you run, block what nobody should, and get an alert when a blocked tool turns up.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-300">
          {notice}
        </p>
      )}

      {data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded border border-gray-700 p-4">
            <div className="text-xs uppercase text-gray-500">Tools detected</div>
            <div className="text-3xl font-semibold text-sky-300" data-testid="tools-found">{data.tools_found}</div>
          </div>
          <div className="rounded border border-gray-700 p-4">
            <div className="text-xs uppercase text-gray-500">Devices with remote tools</div>
            <div className="text-3xl font-semibold text-sky-300" data-testid="devices-with">{reach(data.devices_with_tools, data.devices_scanned)}</div>
            <div className="text-xs text-gray-500">{data.last_scanned ? `Last scan ${when(data.last_scanned)}` : 'CORE has not reported a scan yet'}</div>
          </div>
          <div className="rounded border border-gray-700 p-4">
            <div className="text-xs uppercase text-gray-500">Devices running a blocked tool</div>
            <div className={`text-3xl font-semibold ${data.blocked_devices > 0 ? 'text-red-300' : 'text-gray-200'}`} data-testid="blocked-devices">{data.blocked_devices}</div>
            {data.blocked_devices > 0 && (
              <Link href="/alerts?source=aisoc-remote-tools&status=all" className="text-xs text-sky-300 hover:underline">
                Open their alerts
              </Link>
            )}
          </div>
        </div>
      )}

      {chip && (
        <div role="tablist" aria-label="Show tools by decision" className="flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              role="tab"
              aria-selected={filter === f.value}
              type="button"
              onClick={() => setFilter(f.value)}
              className={`rounded border px-3 py-1 text-sm ${filter === f.value ? 'border-sky-500 text-white' : 'border-gray-700 text-gray-400 hover:text-gray-200'}`}
            >
              {f.label} ({chip[f.value]})
            </button>
          ))}
        </div>
      )}

      {data && data.tools.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="empty">
          {data.last_scanned
            ? 'No remote tools were found on the devices scanned.'
            : 'Nothing has been scanned yet. Once CORE reports the software installed on client devices, the tools found appear here.'}
        </p>
      )}

      {data && data.tools.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="tools-table">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th scope="col" className="py-2 pr-3">Tool</th>
                <th scope="col" className="pr-3">Clients</th>
                <th scope="col" className="pr-3">Devices</th>
                <th scope="col" className="pr-3">Decision</th>
                <th scope="col" className="pr-3">Last seen</th>
                <th scope="col"><span className="sr-only">Decide</span></th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <Fragment key={t.key}>
                  <tr className="border-t border-gray-800 text-gray-200" data-testid={`tool-${t.key}`}>
                    <td className="py-2 pr-3">
                      <button type="button" onClick={() => toggle(t.key)} aria-expanded={open === t.key} className="text-left text-sky-300 hover:underline">
                        {t.name}
                      </button>
                      <div className="text-xs text-gray-500">{categoryLabel(t.category)}</div>
                    </td>
                    <td className="pr-3">{t.clients}</td>
                    <td className="pr-3">
                      {t.devices}
                      {t.blocked_devices > 0 && <span className="ml-1 text-xs text-red-300">({t.blocked_devices} blocked)</span>}
                    </td>
                    <td className="pr-3">
                      <Badge verdict={t.verdict} />
                      {t.client_rules > 0 && <span className="ml-1 text-xs text-gray-500">{t.client_rules} client exception{t.client_rules === 1 ? '' : 's'}</span>}
                    </td>
                    <td className="pr-3 text-xs text-gray-400">{when(t.last_seen)}</td>
                    <td className="space-x-1 whitespace-nowrap text-right">
                      <button type="button" disabled={busy || t.verdict === 'allowed'} onClick={() => void decide(t, 'allowed')} className="rounded border border-emerald-500/40 px-2 py-0.5 text-xs text-emerald-300 disabled:opacity-40" aria-label={`Approve ${t.name}`}>
                        Approve
                      </button>
                      <button type="button" disabled={busy || t.verdict === 'blocked'} onClick={() => void decide(t, 'blocked')} className="rounded border border-red-500/40 px-2 py-0.5 text-xs text-red-300 disabled:opacity-40" aria-label={`Block ${t.name}`}>
                        Block
                      </button>
                      <button type="button" disabled={busy || t.verdict === 'unreviewed'} onClick={() => void decide(t, 'unreviewed')} className="rounded border border-gray-600 px-2 py-0.5 text-xs text-gray-300 disabled:opacity-40" aria-label={`Mark ${t.name} unreviewed`}>
                        Unreview
                      </button>
                    </td>
                  </tr>
                  {open === t.key && (
                    <tr data-testid={`devices-${t.key}`}>
                      <td colSpan={6} className="bg-gray-900/40 px-3 py-2">
                        {devices === null ? (
                          <span className="text-xs text-gray-500">Loading…</span>
                        ) : (
                          <table className="w-full text-xs">
                            <thead className="text-gray-500">
                              <tr>
                                <th scope="col" className="py-1 pr-3 text-left">Client</th>
                                <th scope="col" className="pr-3 text-left">Device</th>
                                <th scope="col" className="pr-3 text-left">Version</th>
                                <th scope="col" className="pr-3 text-left">Decision for this client</th>
                                <th scope="col"><span className="sr-only">Decide for this client</span></th>
                              </tr>
                            </thead>
                            <tbody>
                              {devices.map((d) => (
                                <tr key={`${d.client_id}:${d.hostname}`} className="border-t border-gray-800 text-gray-300">
                                  <td className="py-1 pr-3">{d.client_name ?? '—'}</td>
                                  <td className="pr-3">
                                    <Link href={`/devices?search=${encodeURIComponent(d.hostname)}`} className="text-sky-300 hover:underline">
                                      {d.hostname}
                                    </Link>
                                  </td>
                                  <td className="pr-3">{d.version ?? '—'}</td>
                                  <td className="pr-3"><Badge verdict={d.verdict} /></td>
                                  <td className="space-x-1 whitespace-nowrap text-right">
                                    <button type="button" disabled={busy} onClick={() => void decide(t, 'allowed', { id: d.client_id, name: d.client_name })} className="rounded border border-emerald-500/40 px-1.5 text-emerald-300 disabled:opacity-40" aria-label={`Approve ${t.name} for ${d.client_name ?? 'this client'}`}>
                                      Approve here
                                    </button>
                                    <button type="button" disabled={busy} onClick={() => void decide(t, 'unreviewed', { id: d.client_id, name: d.client_name })} className="rounded border border-gray-600 px-1.5 text-gray-300 disabled:opacity-40" aria-label={`Follow the general decision for ${d.client_name ?? 'this client'}`}>
                                      Follow default
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
