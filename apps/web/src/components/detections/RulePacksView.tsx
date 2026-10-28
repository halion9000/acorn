'use client';

import { useMemo, useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { clsx } from 'clsx';
import { msspApi, type ManagedTenantRow, type RulePackOverview } from '@/lib/api';
import { Skeleton } from '@/components/ui/Skeleton';
import { ErrorState } from '@/components/ui/ErrorState';
import { EmptyState } from '@/components/ui/EmptyState';

/**
 * Rule packs: buckets of detection rules (the imported Sigma rules are grouped by what they watch) that the MSSP applies to the clients it chooses.
 * A pack does nothing for a client until it is ticked here; ticking is what makes the pack's rules part of that client's detections. Nothing is copied into each client.
 */

const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-500/10 text-red-300 ring-red-500/40',
  high: 'bg-orange-500/10 text-orange-300 ring-orange-500/40',
  medium: 'bg-yellow-500/10 text-yellow-300 ring-yellow-500/40',
  low: 'bg-blue-500/10 text-blue-300 ring-blue-500/40',
  info: 'bg-slate-500/10 text-slate-300 ring-slate-500/40',
};

/** The clients whose name contains the search text (all of them when it is empty), by name. */
export function matchingClients(clients: ManagedTenantRow[], search: string): ManagedTenantRow[] {
  const needle = search.trim().toLowerCase();
  return clients.filter((c) => !needle || c.name.toLowerCase().includes(needle)).sort((a, b) => a.name.localeCompare(b.name));
}

export interface ClientPackTotals {
  clientId: string;
  name: string;
  packs: number;
  /** Distinct rules the client gets from its packs (a rule in two of its packs counts once). */
  rules: number;
}

/** What each client gets from the packs applied to it: how many packs and how many distinct rules. Only clients with at least one pack, most rules first, then by name. */
export function clientPackTotals(packs: RulePackOverview[], appliedByPack: Map<string, Set<string>>, clients: ManagedTenantRow[]): ClientPackTotals[] {
  const rulesOf = new Map<string, Set<string>>();
  const packCount = new Map<string, number>();
  for (const pack of packs) {
    for (const clientId of appliedByPack.get(pack.id) ?? []) {
      packCount.set(clientId, (packCount.get(clientId) ?? 0) + 1);
      const set = rulesOf.get(clientId) ?? new Set<string>();
      for (const r of pack.rules) set.add(r.id);
      rulesOf.set(clientId, set);
    }
  }
  const names = new Map(clients.map((c) => [c.tenant_id, c.name]));
  return [...packCount.entries()]
    .map(([clientId, n]) => ({ clientId, name: names.get(clientId) ?? clientId, packs: n, rules: rulesOf.get(clientId)?.size ?? 0 }))
    .sort((a, b) => b.rules - a.rules || a.name.localeCompare(b.name));
}

function PackCard({
  pack,
  clients,
  applied,
  onToggle,
}: {
  pack: RulePackOverview;
  clients: ManagedTenantRow[];
  applied: Set<string>;
  onToggle: (clientId: string, enabled: boolean) => void;
}) {
  const [showRules, setShowRules] = useState(false);
  const [showClients, setShowClients] = useState(false);
  const [search, setSearch] = useState('');
  const shown = useMemo(() => matchingClients(clients, search), [clients, search]);
  return (
    <section aria-label={pack.name} className="space-y-3 rounded-xl border border-gray-800/60 bg-gray-900/40 p-5" data-testid="rule-pack">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-white">{pack.name}</h3>
          {pack.description ? <p className="mt-1 text-sm text-gray-400">{pack.description}</p> : null}
        </div>
        <p className="text-sm text-gray-300" data-testid="pack-applied">
          Applied to <span className="font-semibold tabular-nums">{applied.size}</span> of <span className="tabular-nums">{clients.length}</span> clients
        </p>
      </div>

      <div className="flex flex-wrap gap-4 text-sm">
        <button type="button" onClick={() => setShowRules((v) => !v)} aria-expanded={showRules} className="text-blue-400 hover:text-blue-300">
          {showRules ? 'Hide' : 'Show'} the {pack.rules.length} rule{pack.rules.length === 1 ? '' : 's'}
        </button>
        <button type="button" onClick={() => setShowClients((v) => !v)} aria-expanded={showClients} className="text-blue-400 hover:text-blue-300">
          {showClients ? 'Hide' : 'Choose'} clients
        </button>
      </div>

      {showRules ? (
        <ul className="divide-y divide-gray-800/40 rounded-lg border border-gray-800/60" aria-label={`Rules in ${pack.name}`}>
          {pack.rules.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 truncate text-gray-200">{r.name}</span>
              <span className={clsx('shrink-0 rounded px-2 py-0.5 text-xs ring-1', SEVERITY_BADGE[r.severity] ?? SEVERITY_BADGE.info)}>{r.severity}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {showClients ? (
        <div className="space-y-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search clients…"
            aria-label={`Search clients for ${pack.name}`}
            className="w-full rounded-lg border border-gray-700/60 bg-gray-900 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600"
          />
          <ul className="max-h-64 divide-y divide-gray-800/40 overflow-y-auto rounded-lg border border-gray-800/60">
            {shown.length === 0 ? <li className="px-3 py-2 text-sm text-gray-500">No clients match.</li> : null}
            {shown.map((c) => (
              <li key={c.tenant_id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm text-gray-200 hover:bg-white/[0.02]">
                  <input
                    type="checkbox"
                    checked={applied.has(c.tenant_id)}
                    onChange={(e) => onToggle(c.tenant_id, e.target.checked)}
                    aria-label={`Apply ${pack.name} to ${c.name}`}
                    className="h-4 w-4 rounded border-gray-600 bg-gray-900 accent-blue-500"
                  />
                  {c.name}
                </label>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function RulePacksView() {
  const packs = useSWR('rule-packs', () => msspApi.rulePacks(), { revalidateOnFocus: false, shouldRetryOnError: false });
  const clientList = useSWR('rule-pack-clients', () => msspApi.tenants(false), { revalidateOnFocus: false, shouldRetryOnError: false });
  // A tick shows at once; if saving fails it goes back and says so.
  const [choice, setChoice] = useState<Record<string, boolean>>({});

  const toggle = async (packId: string, clientId: string, enabled: boolean) => {
    const key = `${packId}:${clientId}`;
    setChoice((c) => ({ ...c, [key]: enabled }));
    try {
      await msspApi.setRulePackForClient(packId, clientId, enabled);
    } catch (err) {
      setChoice((c) => {
        const { [key]: _undone, ...rest } = c;
        return rest;
      });
      toast.error(err instanceof Error && err.message ? err.message : 'Could not save that.');
    }
  };

  if (packs.error || clientList.error) {
    return (
      <ErrorState
        title="Couldn't load rule packs"
        description="The rule packs or the client list did not load."
        error={packs.error ?? clientList.error}
        onRetry={() => {
          void packs.mutate();
          void clientList.mutate();
        }}
      />
    );
  }
  if (!packs.data || !clientList.data) return <Skeleton className="h-40 w-full" />;
  if (packs.data.length === 0) {
    return <EmptyState title="No rule packs yet" description="The imported Sigma rules are loaded into packs when the API starts. Restart the API if this stays empty." />;
  }
  const clients = clientList.data;
  // Each pack's applied clients with the ticks that are still being saved laid over them, so the cards and the summary agree.
  const appliedByPack = new Map<string, Set<string>>();
  for (const pack of packs.data) {
    const applied = new Set(pack.applied_to);
    for (const [key, value] of Object.entries(choice)) {
      const [packId, clientId] = key.split(':');
      if (packId !== pack.id) continue;
      if (value) applied.add(clientId);
      else applied.delete(clientId);
    }
    appliedByPack.set(pack.id, applied);
  }
  const totals = clientPackTotals(packs.data, appliedByPack, clients);
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-400">
        A pack is a bucket of detection rules. It does nothing for a client until you tick that client here; ticking makes the pack&rsquo;s rules part of that client&rsquo;s detections.
      </p>
      <section aria-label="What clients get from packs" className="rounded-xl border border-gray-800/60 bg-gray-900/40 p-5" data-testid="pack-totals">
        <h3 className="text-base font-semibold text-white">What clients get from packs</h3>
        {totals.length === 0 ? (
          <p className="mt-1 text-sm text-gray-500">No pack is applied to any client yet. Open a pack, choose clients, and each client you tick shows up here with the rules it gains.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-800/40">
            {totals.slice(0, 15).map((t) => (
              <li key={t.clientId} className="flex items-center justify-between gap-3 py-1.5 text-sm" data-testid="client-pack-total">
                <span className="min-w-0 truncate text-gray-200">{t.name}</span>
                <span className="shrink-0 tabular-nums text-gray-300">
                  +{t.rules} rule{t.rules === 1 ? '' : 's'} from {t.packs} pack{t.packs === 1 ? '' : 's'}
                </span>
              </li>
            ))}
            {totals.length > 15 ? <li className="py-1.5 text-sm text-gray-500">and {totals.length - 15} more clients</li> : null}
          </ul>
        )}
        <p className="mt-2 text-xs text-gray-500">These rules are added to what each client already has; the built-in rules apply to every client as before.</p>
      </section>
      {packs.data.map((pack) => (
        <PackCard key={pack.id} pack={pack} clients={clients} applied={appliedByPack.get(pack.id) ?? new Set()} onToggle={(clientId, enabled) => void toggle(pack.id, clientId, enabled)} />
      ))}
    </div>
  );
}
