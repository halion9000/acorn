'use client';

/**
 * One client's environment: what is there (network gear, computers, cameras, other), which tools cover it, the gaps, and what each network device is plugged into (from Auvik).
 * Everything here is read from what CORE already sent; a client without Auvik shows no cabling and says so.
 */
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import toast from 'react-hot-toast';
import { environmentApi, msspApi, type ChildTenant, type ClientEnvironment } from '@/lib/api';
import { buildMap, type Tier } from './networkMap';
import { downloadText, mapFileName, standaloneSvg } from './mapDownload';

const TIER_FILL: Record<Tier, string> = { 0: '#b45309', 1: '#1d4ed8', 2: '#0f766e', 3: '#4b5563' };
const TIER_NAME: Record<Tier, string> = { 0: 'Firewall / router', 1: 'Switch', 2: 'Access point', 3: 'Other device' };

/** The client's network drawn from Auvik's links. Hover a line for the ports at each end. */
function NetworkMapDrawing({ devices, clientName }: { devices: ClientEnvironment['devices']; clientName: string }) {
  const drawing = useRef<SVGSVGElement>(null);
  const map = buildMap(devices);
  if (map.nodes.length === 0) return null;
  const at = new Map(map.nodes.map((n) => [n.id, n]));
  return (
    <section aria-label="Network map" className="rounded border border-gray-800 p-3" data-testid="network-map">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-gray-200">Network map</h2>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-400">
          <button
            type="button"
            onClick={() => {
              if (drawing.current) downloadText(mapFileName(clientName, new Date()), standaloneSvg(drawing.current), 'image/svg+xml');
            }}
            className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800"
          >
            Download drawing
          </button>
          {([0, 1, 2, 3] as Tier[]).map((t) => (
            <span key={t} className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: TIER_FILL[t] }} />
              {TIER_NAME[t]}
            </span>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg ref={drawing} viewBox={`0 0 ${map.width} ${map.height}`} style={{ minWidth: Math.min(map.width, 900), width: '100%' }} role="img" aria-label="How this client's network devices are connected">
          {map.edges.map((e, i) => {
            const a = at.get(e.from);
            const b = at.get(e.to);
            if (!a || !b) return null;
            return (
              <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#6b7280" strokeWidth={1.5}>
                <title>{`${at.get(e.from)?.label} ↔ ${at.get(e.to)?.label}: ${e.label}${e.speed ? ` · ${e.speed}` : ''}`}</title>
              </line>
            );
          })}
          {map.nodes.map((n) => (
            <g key={n.id} data-testid="map-node" opacity={n.online === false ? 0.45 : 1}>
              <rect x={n.x - 56} y={n.y - 16} width={112} height={32} rx={6} fill={TIER_FILL[n.tier]} stroke="#111827" />
              <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize={11} fill="#f9fafb">
                {n.label.length > 16 ? `${n.label.slice(0, 15)}…` : n.label}
              </text>
              <title>{`${n.label}${n.role ? ` (${n.role})` : ''}${n.online === false ? ' · offline' : ''}`}</title>
            </g>
          ))}
        </svg>
      </div>
      {map.hidden > 0 && <p className="mt-2 text-xs text-gray-500">{map.hidden} more linked devices are in the lists below, not in the drawing.</p>}
    </section>
  );
}

const KINDS: { key: string; label: string }[] = [
  { key: 'network', label: 'Network devices' },
  { key: 'computer', label: 'Computers' },
  { key: 'camera', label: 'Cameras' },
  { key: 'other', label: 'Other' },
];

const TOOL_LABELS: Record<string, string> = {
  ninjaone: 'NinjaOne',
  addigy: 'Addigy',
  huntress: 'Huntress',
  threatmate: 'ThreatMate',
  screenconnect: 'ScreenConnect',
  fieldeffect: 'Field Effect',
  dnsfilter: 'DNSFilter',
  autoelevate: 'AutoElevate',
  auvik: 'Auvik',
};
const toolName = (t: string) => TOOL_LABELS[t] ?? t;

export default function ClientEnvironmentView() {
  const initial = useSearchParams()?.get('client') ?? '';
  const [clients, setClients] = useState<ChildTenant[]>([]);
  const [clientId, setClientId] = useState(initial);
  const [env, setEnv] = useState<ClientEnvironment | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [pushing, setPushing] = useState<string | null>(null);
  const [pushed, setPushed] = useState<Set<string>>(new Set());

  useEffect(() => {
    msspApi
      .listChildren()
      .then(setClients)
      .catch(() => setClients([]));
  }, []);

  useEffect(() => {
    if (!clientId) {
      setEnv(null);
      return;
    }
    let live = true;
    setLoading(true);
    setError('');
    environmentApi
      .get(clientId)
      .then((e) => live && setEnv(e))
      .catch((err) => {
        if (!live) return;
        setEnv(null);
        setError(err instanceof Error && err.message ? err.message : 'Could not load this client');
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [clientId]);

  async function push(deviceId: string, hostname: string) {
    setPushing(deviceId);
    try {
      const out = await environmentApi.push(clientId, deviceId, 'huntress');
      setPushed((p) => new Set(p).add(deviceId));
      toast.success(out.message || `Asked CORE to push Huntress to ${hostname}.`);
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not ask CORE to push it.');
    } finally {
      setPushing(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6" data-testid="client-environment">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-white">Client environment</h1>
        <div className="flex items-center gap-3">
          <Link href="/devices" className="text-sm text-gray-400 hover:text-white">
            All devices
          </Link>
          <select
            aria-label="Client"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white"
          >
            <option value="">Choose a client</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!clientId && <p className="text-sm text-gray-500">Choose a client to see its devices, the tools that cover them and how the network is wired.</p>}
      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}

      {env && (
        <>
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Counts">
            {KINDS.map((k) => (
              <div key={k.key} className="rounded border border-gray-800 p-3">
                <div className="text-2xl font-semibold text-white">{env.counts[k.key] ?? 0}</div>
                <div className="text-xs text-gray-400">{k.label}</div>
              </div>
            ))}
          </section>

          <section className="rounded border border-gray-800 p-3 text-sm" aria-label="Tools">
            <h2 className="mb-2 font-medium text-gray-200">Tools that report this client</h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(env.tools).map(([t, n]) => (
                <span key={t} className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-200">
                  {toolName(t)} · {n}
                </span>
              ))}
              {Object.keys(env.tools).length === 0 && <span className="text-gray-500">No tool has reported a device for this client yet.</span>}
            </div>
            {Object.keys(env.gaps).length > 0 && (
              <p className="mt-3 text-xs text-amber-300" data-testid="env-gaps">
                Computers missing a tool:{' '}
                {Object.entries(env.gaps)
                  .map(([t, n]) => `${toolName(t)} ${n}`)
                  .join(' · ')}
              </p>
            )}
          </section>

          {!env.has_auvik && <p className="text-xs text-gray-500">Auvik has not reported this client, so there is no network wiring to show.</p>}
          {env.has_auvik && !env.has_links && <p className="text-xs text-gray-500">Auvik reports this client but has not named what any device is plugged into.</p>}
          {env.has_links && <NetworkMapDrawing devices={env.devices} clientName={clients.find((c) => c.id === clientId)?.name ?? ''} />}
          {env.truncated &&<p className="text-xs text-amber-300">This client has more devices than are shown here.</p>}

          {KINDS.map((k) => {
            const rows = env.devices.filter((d) => d.kind === k.key);
            if (rows.length === 0) return null;
            return (
              <section key={k.key} aria-label={k.label}>
                <h2 className="mb-2 text-sm font-medium text-gray-200">
                  {k.label} ({rows.length})
                </h2>
                <ul className="divide-y divide-gray-800 rounded border border-gray-800 text-sm">
                  {rows.map((d) => (
                    <li key={d.id} className="space-y-1 p-3" data-testid="env-device">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-gray-100">
                          {d.hostname}
                          {d.role ? <span className="ml-2 text-xs text-gray-500">{d.role}</span> : null}
                        </span>
                        <span className="text-xs text-gray-400">{d.tools.map(toolName).join(', ') || 'no tool'}</span>
                      </div>
                      {d.links.length > 0 && (
                        <ul className="text-xs text-gray-400">
                          {d.links.map((l, i) => (
                            <li key={`${l.name}-${l.port}-${i}`}>
                              {l.port ?? 'port'} → {l.name}
                              {l.remote_port ? ` (${l.remote_port})` : ''}
                              {l.speed ? ` · ${l.speed}` : ''}
                            </li>
                          ))}
                        </ul>
                      )}
                      {d.missing.length > 0 && <div className="text-xs text-amber-300">Missing: {d.missing.map(toolName).join(', ')}</div>}
                      {d.pushable.includes('huntress') && (
                        <button
                          type="button"
                          disabled={pushing === d.id || pushed.has(d.id)}
                          onClick={() => void push(d.id, d.hostname)}
                          className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50"
                          aria-label={`Push Huntress to ${d.hostname} through Addigy`}
                        >
                          {pushed.has(d.id) ? 'Asked CORE' : pushing === d.id ? 'Asking…' : 'Push Huntress through Addigy'}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
