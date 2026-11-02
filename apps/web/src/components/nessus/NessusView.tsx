'use client';

/**
 * Vulnerability scans: upload a Tenable Nessus export (.nessus) for a client, see what it found (worst first, with the CVEs, whether an exploit is known, and the fix), and which scanned hosts are
 * machines we already know. The file is sent as it is (no sign-up form), parsed safely on the server, and kept per client.
 */
import { useRef, useState } from 'react';
import useSWR, { mutate } from 'swr';

import { authApi, msspApi } from '@/lib/api';
import { authFetch } from '@/lib/auth-session';
import { failureDetail } from '@/lib/failure-detail';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';

export interface Scan {
  id: string;
  client_id: string;
  client_name: string;
  name: string;
  description: string | null;
  notes: string | null;
  scan_type: 'lan' | 'wan' | 'other';
  uploaded_by: string | null;
  uploaded_at: string;
  hosts: number;
  matched_hosts: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}
export interface Finding {
  host_name: string;
  host_ip: string | null;
  host_os: string | null;
  device_id: string | null;
  plugin_id: string;
  name: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  port: number;
  protocol: string;
  service: string;
  cvss: number | null;
  cves: string[];
  exploit: boolean;
  synopsis: string;
  solution: string;
}
export interface ScanDetail extends Scan {
  findings: Finding[];
  total_findings: number;
  page: number;
  pages: number;
}

const MAX_MB = 100;
const SEVERITY_STYLE: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-200 ring-red-500/40',
  high: 'bg-orange-500/20 text-orange-200 ring-orange-500/40',
  medium: 'bg-amber-500/20 text-amber-200 ring-amber-500/40',
  low: 'bg-sky-500/20 text-sky-200 ring-sky-500/40',
};

const fetcher = async <T,>(url: string): Promise<T> => {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(await failureDetail(res));
  return res.json();
};

/** The text under a scan: how many hosts, and how many of them are machines we already know. */
export function hostsText(scan: Pick<Scan, 'hosts' | 'matched_hosts'>): string {
  const unmatched = scan.hosts - scan.matched_hosts;
  return `${scan.hosts} host${scan.hosts === 1 ? '' : 's'}: ${scan.matched_hosts} in inventory${unmatched > 0 ? `, ${unmatched} not in inventory` : ''}`;
}

function Chip({ label, count, tone }: { label: string; count: number; tone: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${count > 0 ? SEVERITY_STYLE[tone] : 'bg-gray-800 text-gray-500 ring-gray-700'}`}>
      {count} {label}
    </span>
  );
}

function Upload({ clients, onDone }: { clients: { id: string; name: string }[]; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [client, setClient] = useState(clients[0]?.id ?? '');
  const [name, setName] = useState('');
  const [type, setType] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const send = async (file: File) => {
    setError(null);
    setDone(null);
    if (!client) return setError('Choose the client this scan is about.');
    if (file.size > MAX_MB * 1024 * 1024) return setError(`That file is larger than ${MAX_MB} MB.`);
    if (!/\.nessus$/i.test(file.name)) return setError('Choose a .nessus file (in Nessus: export the scan as "Nessus").');
    setBusy(true);
    try {
      const params = new URLSearchParams({ client_id: client });
      if (name.trim()) params.set('name', name.trim());
      if (type) params.set('scan_type', type);
      const res = await authFetch(`/api/v1/nessus/scans?${params}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      if (!res.ok) throw new Error(await failureDetail(res));
      const scan = (await res.json()) as Scan;
      setDone(`Added "${scan.name}": ${scan.hosts} hosts, ${scan.critical} critical and ${scan.high} high findings.`);
      setName('');
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The upload failed.');
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  return (
    <section aria-label="Upload a scan" className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h2 className="text-sm font-semibold text-gray-100">Upload a Nessus scan</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-gray-400">
          Client
          <select aria-label="Client" value={client} onChange={(e) => setClient(e.target.value)} className="mt-1 block w-full rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-sm text-gray-100">
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Name (optional)
          <input aria-label="Scan name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Monthly internal scan" className="mt-1 block w-full rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-sm text-gray-100" />
        </label>
        <label className="text-xs text-gray-400">
          Scan type
          <select aria-label="Scan type" value={type} onChange={(e) => setType(e.target.value)} className="mt-1 block w-full rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-sm text-gray-100">
            <option value="">Detect automatically</option>
            <option value="lan">LAN (inside the network)</option>
            <option value="wan">WAN (from the internet)</option>
            <option value="other">Other</option>
          </select>
        </label>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          ref={input}
          type="file"
          accept=".nessus,application/xml,text/xml"
          aria-label="Choose a .nessus file"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
          }}
          className="text-sm text-gray-300 file:mr-3 file:rounded-lg file:border file:border-gray-700 file:bg-gray-900 file:px-3 file:py-1.5 file:text-sm file:text-gray-200"
        />
        <span className="text-xs text-gray-500">A .nessus export, up to {MAX_MB} MB. Informational findings are left out.</span>
      </div>
      {busy ? (
        <p role="status" className="mt-3 text-sm text-gray-400">
          Reading the file…
        </p>
      ) : null}
      {done ? (
        <p role="status" className="mt-3 text-sm text-emerald-300">
          {done}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function Detail({ scanId, onClose }: { scanId: string; onClose: () => void }) {
  const [severity, setSeverity] = useState('');
  const [host, setHost] = useState('');
  const [page, setPage] = useState(1);
  const qs = new URLSearchParams({ page: String(page), page_size: '25' });
  if (severity) qs.set('severity', severity);
  if (host.trim()) qs.set('host', host.trim());
  const { data, error } = useSWR<ScanDetail>(`/api/v1/nessus/scans/${scanId}?${qs}`, fetcher, { shouldRetryOnError: false, keepPreviousData: true });
  return (
    <section aria-label="Scan findings" className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-gray-100">{data?.name ?? 'Scan'}</h3>
        <button type="button" onClick={onClose} className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-800">
          Close
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : !data ? (
        <p className="mt-3 text-sm text-gray-500">Loading…</p>
      ) : (
        <>
          <p className="mt-1 text-sm text-gray-400">{hostsText(data)}. Worst first; a known exploit ranks above the same severity without one.</p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-xs text-gray-400">
              Severity
              <select aria-label="Severity" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }} className="ml-2 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100">
                <option value="">All</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
            <label className="text-xs text-gray-400">
              Host
              <input aria-label="Host" value={host} onChange={(e) => { setHost(e.target.value); setPage(1); }} placeholder="name or address" className="ml-2 w-44 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100" />
            </label>
          </div>
          {data.findings.length === 0 ? (
            <p className="mt-4 text-sm text-gray-400">No findings match.</p>
          ) : (
            <div className="mt-3 overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-900/60 text-xs text-gray-400">
                  <tr>
                    <th className="px-3 py-2">Severity</th>
                    <th className="px-3 py-2">Finding</th>
                    <th className="px-3 py-2">Host</th>
                    <th className="px-3 py-2">Port</th>
                    <th className="px-3 py-2">CVSS</th>
                    <th className="px-3 py-2">Fix</th>
                  </tr>
                </thead>
                <tbody>
                  {data.findings.map((f, i) => (
                    <tr key={`${f.host_name}-${f.plugin_id}-${f.port}-${i}`} data-testid="finding-row" className="border-t border-gray-800 align-top">
                      <td className="px-3 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${SEVERITY_STYLE[f.severity]}`}>{f.severity}</span>
                        {f.exploit ? <span className="ml-1 rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">exploit</span> : null}
                      </td>
                      <td className="px-3 py-2 text-gray-100">
                        <div>{f.name}</div>
                        {f.cves.length > 0 ? <div className="mt-0.5 font-mono text-xs text-gray-400">{f.cves.slice(0, 4).join(', ')}{f.cves.length > 4 ? ` +${f.cves.length - 4}` : ''}</div> : null}
                      </td>
                      <td className="px-3 py-2 text-gray-200">
                        <div>{f.host_name}</div>
                        <div className={`text-xs ${f.device_id ? 'text-emerald-300' : 'text-gray-500'}`}>{f.device_id ? 'in inventory' : 'not in inventory'}</div>
                      </td>
                      <td className="px-3 py-2 text-gray-300">{f.port ? `${f.port}/${f.protocol}` : '—'}</td>
                      <td className="px-3 py-2 text-gray-300">{f.cvss ?? '—'}</td>
                      <td className="max-w-xs px-3 py-2 text-xs text-gray-400">{f.solution || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.pages > 1 ? (
            <div className="mt-3 flex items-center gap-3 text-sm text-gray-400">
              <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-gray-700 px-2 py-1 disabled:opacity-40">
                Previous
              </button>
              <span data-testid="page-info">
                {data.total_findings} findings · page {data.page} of {data.pages}
              </span>
              <button type="button" disabled={page >= data.pages} onClick={() => setPage(page + 1)} className="rounded border border-gray-700 px-2 py-1 disabled:opacity-40">
                Next
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

export function NessusView() {
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Scan | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const listKey = `/api/v1/nessus/scans${filter ? `?client_id=${filter}` : ''}`;
  const { data: scans, error, isLoading } = useSWR<Scan[]>(listKey, fetcher, { shouldRetryOnError: false });
  const { data: clients = [] } = useSWR<{ id: string; name: string }[]>('nessus-clients', async () => {
    const own = authApi.currentUser();
    const children = await msspApi.listChildren().catch(() => []);
    const list = (children as { id: string; name: string }[]).map((c) => ({ id: c.id, name: c.name })).sort((a, b) => a.name.localeCompare(b.name));
    return own?.tenant_id ? [{ id: own.tenant_id, name: 'Live Oak (own)' }, ...list] : list;
  });

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setDeleteError(null);
    try {
      const res = await authFetch(`/api/v1/nessus/scans/${deleting.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await failureDetail(res));
      if (open === deleting.id) setOpen(null);
      setDeleting(null);
      await mutate((k) => typeof k === 'string' && k.startsWith('/api/v1/nessus/scans'));
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'The scan could not be deleted.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Vulnerability scans</h1>
        <p className="mt-1 text-sm text-gray-400">Upload a Nessus export for a client and see what it found, worst first, and which of the scanned machines we already know.</p>
      </div>
      {clients.length > 0 ? <Upload clients={clients} onDone={() => void mutate((k) => typeof k === 'string' && k.startsWith('/api/v1/nessus/scans'))} /> : null}
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-400">
          Show
          <select aria-label="Show scans for" value={filter} onChange={(e) => setFilter(e.target.value)} className="ml-2 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100">
            <option value="">Every client</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading || !scans ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : scans.length === 0 ? (
        <p className="rounded-lg border border-gray-800 px-4 py-6 text-sm text-gray-400">No scans uploaded yet. Export a scan from Nessus as a .nessus file and upload it above.</p>
      ) : (
        <ul className="divide-y divide-gray-800 rounded-lg border border-gray-800">
          {scans.map((s) => (
            <li key={s.id} data-testid="scan-row" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-gray-100">
                  {s.name} <span className="ml-1 rounded bg-gray-700 px-1.5 py-0.5 text-[10px] font-bold uppercase text-gray-200">{s.scan_type}</span>
                </p>
                <p className="text-xs text-gray-400">
                  {s.client_name} · {new Date(s.uploaded_at).toLocaleDateString()} · {hostsText(s)}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Chip label="critical" count={s.critical} tone="critical" />
                <Chip label="high" count={s.high} tone="high" />
                <Chip label="medium" count={s.medium} tone="medium" />
                <Chip label="low" count={s.low} tone="low" />
                <button type="button" onClick={() => setOpen(open === s.id ? null : s.id)} aria-label={`View ${s.name}`} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800">
                  {open === s.id ? 'Close' : 'View'}
                </button>
                <button type="button" onClick={() => { setDeleting(s); setDeleteError(null); }} aria-label={`Delete ${s.name}`} className="rounded px-2 py-1 text-xs text-red-300 hover:bg-gray-800">
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {open ? <Detail scanId={open} onClose={() => setOpen(null)} /> : null}
      <ConfirmDialog
        open={deleting !== null}
        title={deleteError ? 'Could not delete' : 'Delete this scan?'}
        message={deleteError ?? `${deleting?.name ?? 'This scan'} and all of its findings are removed. This cannot be undone. It is written to the audit log.`}
        confirmLabel={deleteError ? 'Close' : 'Delete'}
        destructive={!deleteError}
        busy={busy}
        onConfirm={() => (deleteError ? setDeleting(null) : void remove())}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
