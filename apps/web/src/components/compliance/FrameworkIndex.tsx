'use client';

/**
 * The Compliance index: a card for each framework, with a "Whose compliance" choice above them. A client chosen here goes with every card's link (`?client=<id>`), so the framework page opens on that
 * client and not on the organisation's own evidence. The choice is also written into this page's address, so a reload or a shared link keeps it. An organisation with no clients sees no choice.
 */
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { authFetch } from '@/lib/auth-session';
import { SecureframeCard } from './SecureframeCard';

export interface FrameworkCard {
  id: string;
  name: string;
  description: string;
  badge: string;
}

/** The framework page's address, for one client when one is chosen. */
export function frameworkHref(frameworkId: string, clientId: string): string {
  return clientId ? `/compliance/${frameworkId}?client=${encodeURIComponent(clientId)}` : `/compliance/${frameworkId}`;
}

/** The framework keys the API reports by, for the ids on this page. */
export const FRAMEWORK_KEYS: Record<string, string> = { soc2: 'SOC2', iso27001: 'ISO27001', nist_csf: 'NIST-CSF', pci_dss: 'PCI-DSS', hipaa: 'HIPAA' };

interface PostureRow {
  framework: string;
  controls_covered: string[];
  controls_missing: string[];
}

/** How far along a framework is: the controls with accepted evidence over all its controls. Null when the API listed no controls. */
export function completion(row: Pick<PostureRow, 'controls_covered' | 'controls_missing'> | undefined): { pct: number; covered: number; total: number } | null {
  if (!row) return null;
  const covered = row.controls_covered.length;
  const total = covered + row.controls_missing.length;
  return total === 0 ? null : { pct: Math.round((covered / total) * 100), covered, total };
}

function Progress({ value }: { value: { pct: number; covered: number; total: number } | null | undefined }) {
  if (value === undefined) return <p className="mt-4 text-xs text-gray-500">Reading progress…</p>;
  if (value === null) return <p className="mt-4 text-xs text-gray-500">Progress is not available.</p>;
  return (
    <div className="mt-4" data-testid="framework-progress">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-medium text-gray-200">{value.pct}% complete</span>
        <span className="text-gray-500">
          {value.covered} of {value.total} controls have accepted evidence
        </span>
      </div>
      <div role="progressbar" aria-label="Controls with accepted evidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value.pct} className="h-1.5 overflow-hidden rounded-full bg-gray-700">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${value.pct}%` }} />
      </div>
    </div>
  );
}

export function FrameworkIndex({ frameworks }: { frameworks: FrameworkCard[] }) {
  const [clientId, setClientId] = useState('');
  // A link can open on one client; read once, after the first paint so the server and browser markup agree.
  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  // How far along each framework is, for the chosen client (or the organization). undefined while reading, null when it could not be read.
  const [posture, setPosture] = useState<Record<string, { pct: number; covered: number; total: number } | null> | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    setPosture(undefined);
    (async () => {
      try {
        const res = await authFetch(clientId ? `/api/v1/compliance/report?client_id=${encodeURIComponent(clientId)}` : '/api/v1/compliance/report');
        if (!res.ok) throw new Error(String(res.status));
        const rows = (await res.json()) as PostureRow[];
        if (live) setPosture(Object.fromEntries(rows.map((r) => [r.framework, completion(r)])));
      } catch {
        if (live) setPosture(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);

  const choose = (id: string) => {
    setClientId(id);
    try {
      window.history.replaceState(null, '', id ? `?client=${encodeURIComponent(id)}` : window.location.pathname);
    } catch {
      // the address cannot be changed here; the choice still applies to the links below
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Compliance Frameworks</h1>
        <p className="text-gray-400 text-sm mt-1">Select a framework to view controls, collect evidence, and export reports.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={choose} label="Whose compliance" />
        </div>
      </div>

      {!clientId && <SecureframeCard />}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {frameworks.map((fw) => (
          <Link
            key={fw.id}
            href={frameworkHref(fw.id, clientId)}
            className="block bg-gray-800 border border-gray-700 rounded-lg p-5 hover:border-blue-500 hover:bg-gray-750 transition-all group"
          >
            <div className="flex items-start justify-between mb-3">
              <h2 className="text-white font-semibold text-base group-hover:text-blue-400 transition-colors">{fw.name}</h2>
              <span className="ml-2 flex-shrink-0 text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">{fw.badge}</span>
            </div>
            <p className="text-gray-400 text-sm leading-relaxed">{fw.description}</p>
            <Progress value={posture === undefined ? undefined : posture === null ? null : (posture[FRAMEWORK_KEYS[fw.id] ?? fw.id] ?? null)} />
            <div className="mt-4 text-blue-400 text-xs font-medium group-hover:text-blue-300">View Dashboard →</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
