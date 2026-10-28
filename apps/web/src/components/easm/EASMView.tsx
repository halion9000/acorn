'use client';

/**
 * External Attack Surface Management: what A.C.O.R.N has discovered about the organisation from outside, and what changed since the last scan.
 *
 * Backed by /api/v1/easm/{assets,drift,scan}. The certificate inventory the old placeholder promised has no endpoint; certificate changes appear here as drift events.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

interface Asset {
  id: string;
  asset_type: string;
  value: string;
  first_seen: string;
  last_seen: string;
  metadata: Record<string, unknown> | null;
}
interface Drift {
  id: string;
  external_asset_id: string;
  drift_type: string;
  details: Record<string, unknown> | null;
  detected_at: string;
}

export interface AssetFindings {
  /** The addresses a domain resolves to. */
  resolvesTo: string[];
  ports: number[];
  /** Known vulnerabilities (CVE ids) the lookup lists for the address. */
  vulns: string[];
  tags: string[];
  hostnames: string[];
}

const textList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '') : []);

/** What a scan recorded about one asset (the lookup's open ports, vulnerabilities, tags and hostnames; the addresses a domain resolves to), read defensively: anything missing is empty. */
export function findingsOf(metadata: Record<string, unknown> | null | undefined): AssetFindings {
  const m = metadata ?? {};
  const ports = Array.isArray(m.ports) ? m.ports.filter((p): p is number => typeof p === 'number').sort((a, b) => a - b) : [];
  return { resolvesTo: textList(m.resolved_ips), ports, vulns: textList(m.vulns), tags: textList(m.tags), hostnames: textList(m.hostnames) };
}

const HOSTNAMES_SHOWN = 3;

function Findings({ asset }: { asset: Asset }) {
  const f = findingsOf(asset.metadata);
  const rows: { label: string; value: string; tone?: string }[] = [];
  if (f.resolvesTo.length) rows.push({ label: 'Resolves to', value: f.resolvesTo.join(', ') });
  if (f.ports.length) rows.push({ label: 'Open ports', value: f.ports.join(', ') });
  if (f.vulns.length) rows.push({ label: 'Known vulnerabilities', value: f.vulns.join(', '), tone: 'text-red-400' });
  if (f.tags.length) rows.push({ label: 'Tags', value: f.tags.join(', ') });
  if (f.hostnames.length) {
    const more = f.hostnames.length - HOSTNAMES_SHOWN;
    rows.push({ label: 'Hostnames', value: f.hostnames.slice(0, HOSTNAMES_SHOWN).join(', ') + (more > 0 ? ` and ${more} more` : '') });
  }
  if (rows.length === 0) return <span className="text-gray-600">{asset.asset_type === 'ip' ? 'Nothing listed for this address' : '—'}</span>;
  return (
    <ul className="space-y-0.5" data-testid="asset-findings">
      {rows.map((r) => (
        <li key={r.label} className="text-xs">
          <span className="text-gray-500">{r.label}: </span>
          <span className={r.tone ?? 'text-gray-300'}>{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

/** The public IP addresses and domain names typed in the box: separated by commas, spaces or new lines, blanks and repeats dropped. */
export function parseTargets(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean))];
}

interface ScanStatus {
  plan: { shodan: boolean; censys: boolean; port_check: boolean; sources: string[]; can_run: boolean; problem: string | null };
  last_scan: { started_at?: string; finished_at?: string; found?: number; changes?: number; error?: string | null; sources?: string[] } | null;
}

/** One sentence on how the last scan went, for under the Run button. */
export function lastScanText(last: ScanStatus['last_scan']): string | null {
  if (!last) return null;
  const when = last.finished_at ? new Date(last.finished_at).toLocaleString() : 'recently';
  if (last.error) return `The last scan (${when}) failed: ${last.error}`;
  const using = last.sources && last.sources.length > 0 ? ` using ${last.sources.join(' and ')}` : '';
  const found = last.found ?? 0;
  return found === 0
    ? `The last scan (${when})${using} finished and found nothing.`
    : `The last scan (${when})${using} found ${found} asset${found === 1 ? '' : 's'} and ${last.changes ?? 0} change${last.changes === 1 ? '' : 's'}.`;
}

async function refusal(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const first = Array.isArray(body.detail) ? (body.detail[0] as { msg?: string } | undefined)?.msg : body.detail;
    if (typeof first === 'string' && first) return first.replace(/^Value error, /, '');
  } catch {
    // no readable reason: fall through
  }
  return 'That was not accepted. Only public IP addresses and domain names are allowed (no ranges or internal addresses).';
}

async function getJson<T>(path: string): Promise<T> {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as T;
}

export function EASMView() {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [drift, setDrift] = useState<Drift[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [targets, setTargets] = useState('');
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, d] = await Promise.all([getJson<Asset[]>('/api/v1/easm/assets?limit=200'), getJson<Drift[]>('/api/v1/easm/drift?limit=50')]);
      setAssets(a);
      setDrift(d);
      setError(null);
      try {
        const st = await getJson<ScanStatus>('/api/v1/easm/status');
        setScanStatus(st && typeof st === 'object' && 'plan' in st ? st : null);
      } catch {
        setScanStatus(null); // an older API has no status: the page works without it
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the attack surface');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function scan() {
    setScanning(true);
    setNote(null);
    try {
      const res = await authFetch('/api/v1/easm/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ip_targets: parseTargets(targets) }) });
      if (res.status === 422) throw new Error(await refusal(res));
      if (res.status === 403) throw new Error('EASM is disabled for this deployment, or your role cannot start a scan.');
      if (res.status === 409) throw new Error(await refusal(res));
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setNote('Scan started. The result appears below when it finishes.');
      // The scan runs in the background: check back until it records its outcome.
      const before = scanStatus?.last_scan?.finished_at ?? null;
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const fresh = await getJson<ScanStatus>('/api/v1/easm/status').catch(() => null);
        if (fresh?.last_scan?.finished_at && fresh.last_scan.finished_at !== before) {
          setScanStatus(fresh);
          setNote(null);
          await load();
          break;
        }
      }
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Could not start the scan');
    } finally {
      setScanning(false);
    }
  }

  const byType = (assets ?? []).reduce<Record<string, number>>((acc, a) => ({ ...acc, [a.asset_type]: (acc[a.asset_type] ?? 0) + 1 }), {});

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">External Attack Surface Management</h1>
          <p className="text-sm text-gray-400 mt-1">What A.C.O.R.N can see of your organisation from the internet, and what changed.</p>
        </div>
        <button type="button" onClick={() => void scan()} disabled={scanning} className="px-3 py-2 rounded bg-blue-600 text-white text-sm disabled:opacity-50">
          {scanning ? 'Starting...' : 'Run a scan'}
        </button>
      </div>

      <div>
        <label htmlFor="easm-targets" className="block text-sm text-gray-300">
          Domain names or public IP addresses to check (optional)
        </label>
        <textarea
          id="easm-targets"
          value={targets}
          onChange={(e) => setTargets(e.target.value)}
          rows={2}
          placeholder="acme.com, 203.0.113.10"
          className="mt-1 w-full max-w-xl rounded border border-gray-700 bg-gray-900 px-2 py-1 font-mono text-sm text-gray-100"
        />
        <p className="mt-1 text-xs text-gray-500">
          Separate with commas, spaces or new lines. Leave it empty to use the domains of the people held for this tenant. A domain is looked up through its public addresses in Shodan&apos;s free InternetDB (open ports, known CVEs). Only IP addresses typed here are probed for open ports, and only when the server has <span className="font-mono">AISOC_EASM_ACTIVE_SCAN_ENABLED=true</span> (off by default).
        </p>
      </div>

      {scanStatus && (
        <div className="rounded border border-gray-800 bg-gray-900/50 p-3 text-sm text-gray-300" data-testid="scan-status">
          <p>
            Discovery sources set up on this server:{' '}
            {[scanStatus.plan.shodan ? 'Shodan' : null, scanStatus.plan.censys ? 'Censys' : null, scanStatus.plan.port_check ? 'port check (for the addresses you enter)' : null].filter(Boolean).join(', ') || 'none'}
          </p>
          {!scanStatus.plan.can_run && scanStatus.plan.problem && <p className="mt-1 text-amber-300">{scanStatus.plan.problem}</p>}
          {lastScanText(scanStatus.last_scan) && <p className="mt-1 text-gray-400">{lastScanText(scanStatus.last_scan)}</p>}
        </div>
      )}

      {note && <p className="text-sm text-gray-300">{note}</p>}
      {error && (
        <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
      {assets === null && !error && <p className="text-sm text-gray-500">Loading...</p>}

      {assets !== null && (
        <>
          <p className="text-sm text-gray-400" data-testid="asset-summary">
            {assets.length === 0
              ? 'No external assets discovered yet. Run a scan (it needs a Shodan or Censys key, or IP targets, configured).'
              : `${assets.length} external asset(s): ${Object.entries(byType)
                  .map(([t, n]) => `${n} ${t}`)
                  .join(', ')}`}
          </p>

          {assets.length > 0 && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-500">
                  <th className="py-2">Type</th>
                  <th>Asset</th>
                  <th>What we found</th>
                  <th>First seen</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => (
                  <tr key={a.id} className="border-b border-gray-800">
                    <td className="py-2 text-gray-400">{a.asset_type}</td>
                    <td className="font-mono text-gray-200">{a.value}</td>
                    <td className="py-2 pr-3">
                      <Findings asset={a} />
                    </td>
                    <td className="text-gray-500">{new Date(a.first_seen).toLocaleDateString()}</td>
                    <td className="text-gray-500">{new Date(a.last_seen).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div>
            <h2 className="text-base font-semibold text-gray-200 mb-2">Recent changes</h2>
            {drift.length === 0 ? (
              <p className="text-sm text-gray-500">Nothing has changed since the first scan.</p>
            ) : (
              <ul className="space-y-2">
                {drift.map((d) => {
                  const asset = assets.find((a) => a.id === d.external_asset_id);
                  return (
                    <li key={d.id} className="text-sm text-gray-300">
                      <span className="text-yellow-400">{d.drift_type}</span> on <span className="font-mono">{asset?.value ?? d.external_asset_id}</span>
                      <span className="text-gray-500"> · {new Date(d.detected_at).toLocaleString()}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
