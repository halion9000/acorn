'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import useSWR from 'swr';
import { safeDistance } from '@/lib/safe-date';
import { alertsApi, type Alert } from '@/lib/api';
import { authFetch } from '@/lib/auth-session';

/** The newest critical and high alerts nobody has picked up yet, newest first. */
export function needsAttention(critical: Alert[], high: Alert[], limit = 6): Alert[] {
  return [...critical, ...high].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, limit);
}

/** A billed line counts when it disagrees with the tool counts and nobody has accepted that difference. */
export interface BillingRow {
  client_id: string;
  difference: number;
  note_state?: string;
}

/** How many days a line must have disagreed before it is worth a notification. */
export const BILLING_DAYS = 14;

/** The lines that disagree and are not accepted, and how many clients they are for. */
export function billingLinesOff(rows: BillingRow[]): { lines: number; clients: number } {
  const off = rows.filter((r) => r.difference !== 0 && r.note_state !== 'accepted');
  return { lines: off.length, clients: new Set(off.map((r) => r.client_id)).size };
}

/** One approval CORE says is waiting for the owner (agent, one-line summary, whole days before CORE takes it off the list). */
export interface CoreApproval {
  role: string;
  summary: string;
  days_left: number;
}

/** What the bell says about CORE's waiting approvals: how many, and the one closest to expiring (the list arrives fewest-days-left first). Nothing to say when none wait. */
export function approvalsLine(items: CoreApproval[]): { title: string; detail: string } | null {
  if (items.length === 0) return null;
  const first = items[0];
  const days = first.days_left <= 0 ? 'expires today' : first.days_left === 1 ? 'expires in 1 day' : `expires in ${first.days_left} days`;
  return {
    title: `${items.length} approval${items.length === 1 ? '' : 's'} waiting in CORE`,
    detail: `${first.role}: ${first.summary} (${days}). Answer in the CORE app.`,
  };
}

/** One BEC search that finished (or failed) in the last day. */
export interface BecFinished {
  id: string;
  client_name: string;
  email: string;
  status: 'done' | 'failed';
  level?: string | null;
  ticket_id?: string | null;
}

/** How a finished search reads in the bell: CIPP's own rating when it gave one, or plainly that it did not finish. Never says "clean". */
export function becFinishedLine(b: BecFinished): { title: string; detail: string } {
  const where = b.client_name ? ` · ${b.client_name}` : '';
  const ticket = b.ticket_id ? ` · ticket ${b.ticket_id}` : '';
  if (b.status === 'failed') return { title: `BEC search for ${b.email} did not finish`, detail: `Start it again from Identities${where}${ticket}` };
  return { title: `BEC search for ${b.email} finished`, detail: `${b.level ? `CIPP rates it ${b.level}` : 'CIPP gave no rating'}${where}${ticket}` };
}

/** Where a finished search's row goes: the person it was for (the Identities page opens the one person a ?search= finds), or the whole list when the row names nobody. */
export function becHref(b: Pick<BecFinished, 'email'>): string {
  const email = (b.email ?? '').trim();
  return email ? `/identities?search=${encodeURIComponent(email)}` : '/identities';
}

/** A connected tool as the connectors list sends it, reduced to what the bell reads. */
export interface ConnectorFreshness {
  name: string;
  is_enabled?: boolean;
  freshness?: { status?: string } | null;
}

/**
 * The bell line for tools that have gone quiet: switched-on connectors whose last event is older than their own expected cadence (the server's red verdict). A tool that has never had an event
 * ("unknown") is a tool still being set up, not a quiet one, and a yellow one is merely slow: neither is counted. Null when none are quiet.
 */
export function quietToolsLine(connectors: ConnectorFreshness[]): { title: string; detail: string } | null {
  const quiet = connectors.filter((c) => c.is_enabled !== false && c.freshness?.status === 'red').map((c) => c.name).sort((a, b) => a.localeCompare(b));
  if (quiet.length === 0) return null;
  const shown = quiet.slice(0, 3).join(', ');
  const more = quiet.length > 3 ? ` and ${quiet.length - 3} more` : '';
  return {
    title: quiet.length === 1 ? '1 connected tool has gone quiet' : `${quiet.length} connected tools have gone quiet`,
    detail: `${shown}${more}: nothing has come in for longer than usual`,
  };
}

const BEC_SEEN_KEY = 'bell-bec-seen';

function readSeen(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(BEC_SEEN_KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function writeSeen(ids: string[]): void {
  try {
    window.localStorage.setItem(BEC_SEEN_KEY, JSON.stringify(ids.slice(-50)));
  } catch {
    /* private window or blocked storage: the dot simply shows again */
  }
}

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { data, error, isLoading } = useSWR(
    'topbar-notifications',
    async () => {
      const [critical, high] = await Promise.all([
        alertsApi.list({ severity: 'critical', status: 'new', pageSize: 6 }),
        alertsApi.list({ severity: 'high', status: 'new', pageSize: 6 }),
      ]);
      return { criticalCount: critical.total, highCount: high.total, items: needsAttention(critical.alerts, high.alerts) };
    },
    { refreshInterval: 60_000, shouldRetryOnError: false },
  );

  // Billing lines that have disagreed with the tool counts for two weeks or more. A person without billing access, or a failed read, simply gets no billing line.
  const { data: billing } = useSWR(
    'topbar-billing',
    async () => {
      const res = await authFetch(`/api/v1/billing/reconcile?min_days=${BILLING_DAYS}&limit=1000`);
      if (!res.ok) return null;
      const body = (await res.json()) as { rows?: BillingRow[] };
      return billingLinesOff(Array.isArray(body.rows) ? body.rows : []);
    },
    { refreshInterval: 300_000, shouldRetryOnError: false },
  );

  // Connected tools whose events have stopped coming in. A person who cannot read connectors, or a failed read, simply gets no such line.
  const { data: quiet } = useSWR(
    'topbar-quiet-tools',
    async () => {
      const res = await authFetch('/api/v1/connectors');
      if (!res.ok) return null;
      const body = (await res.json()) as ConnectorFreshness[] | { connectors?: ConnectorFreshness[] };
      return quietToolsLine(Array.isArray(body) ? body : Array.isArray(body.connectors) ? body.connectors : []);
    },
    { refreshInterval: 300_000, shouldRetryOnError: false },
  );

  // Approvals CORE says are waiting for the owner, as of its last report. A person without alert access, a failed read, or a CORE that has not reported lately simply gets no approvals line.
  const { data: coreApprovals } = useSWR(
    'topbar-core-approvals',
    async () => {
      const res = await authFetch('/api/v1/health/core-approvals');
      if (!res.ok) return null;
      const body = (await res.json()) as { items?: CoreApproval[] };
      return Array.isArray(body.items) ? body.items : [];
    },
    { refreshInterval: 120_000, shouldRetryOnError: false },
  );

  // BEC searches that finished in the last day, so a person who started one need not watch it. A person without the BEC permission or a failed read gets no such line.
  const { data: becDone } = useSWR(
    'topbar-bec-finished',
    async () => {
      const res = await authFetch('/api/v1/identities/bec/finished');
      if (!res.ok) return null;
      const body = (await res.json()) as { items?: BecFinished[] };
      return Array.isArray(body.items) ? body.items : [];
    },
    { refreshInterval: 60_000, shouldRetryOnError: false },
  );
  const [seen, setSeen] = useState<string[]>([]);
  useEffect(() => setSeen(readSeen()), []);
  const becItems = becDone ?? [];
  const becUnseen = becItems.filter((b) => !seen.includes(b.id)).length;
  useEffect(() => {
    // Opening the bell is reading it: the dot goes, the rows stay until they are a day old.
    if (!open || becItems.length === 0) return;
    const all = Array.from(new Set([...readSeen(), ...becItems.map((b) => b.id)]));
    writeSeen(all);
    setSeen(all);
  }, [open, becItems.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const criticalCount = data?.criticalCount ?? 0;
  const total = criticalCount + (data?.highCount ?? 0);
  const billingLines = billing?.lines ?? 0;
  const approvals = approvalsLine(coreApprovals ?? []);

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-label="Open notifications"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="relative p-1.5 text-fg-muted hover:text-fg-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
        </svg>
        {criticalCount > 0 ? (
          <span aria-hidden data-testid="bell-dot" className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full ring-2 ring-surface-raised" />
        ) : becUnseen > 0 ? (
          <span aria-hidden data-testid="bell-dot-bec" className="absolute top-1 right-1 w-2 h-2 bg-blue-400 rounded-full ring-2 ring-surface-raised" />
        ) : approvals ? (
          <span aria-hidden data-testid="bell-dot-approvals" className="absolute top-1 right-1 w-2 h-2 bg-amber-400 rounded-full ring-2 ring-surface-raised" />
        ) : billingLines > 0 ? (
          <span aria-hidden data-testid="bell-dot-billing" className="absolute top-1 right-1 w-2 h-2 bg-amber-400 rounded-full ring-2 ring-surface-raised" />
        ) : null}
      </button>

      {open ? (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 mt-2 w-80 rounded-xl border border-gray-800 bg-gray-900 shadow-xl z-50">
          <div className="px-4 py-3 border-b border-gray-800">
            <p className="text-sm font-medium text-gray-100">Needs attention</p>
            <p className="text-xs text-gray-500">
              {error ? 'Could not load alerts.' : isLoading ? 'Loading…' : total === 0 ? 'No new critical or high alerts.' : `${criticalCount} critical, ${data?.highCount ?? 0} high, not yet picked up`}
            </p>
          </div>
          {data && data.items.length > 0 ? (
            <ul className="max-h-80 overflow-auto divide-y divide-gray-800/60">
              {data.items.map((a) => (
                <li key={a.id}>
                  <Link href={`/alerts/${a.id}`} onClick={() => setOpen(false)} className="block px-4 py-2.5 hover:bg-gray-800/50">
                    <p className="text-sm text-gray-200 truncate">{a.title}</p>
                    <p className="text-xs text-gray-500">
                      <span className={a.severity === 'critical' ? 'text-red-400' : 'text-orange-400'}>{a.severity}</span>
                      {a.clientName ? ` · ${a.clientName}` : ''} · {safeDistance(a.createdAt, { addSuffix: true })}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
          {becItems.length > 0 ? (
            <ul data-testid="bell-bec" className="divide-y divide-gray-800/60 border-t border-gray-800">
              {becItems.map((b) => {
                const line = becFinishedLine(b);
                return (
                  <li key={b.id}>
                    <Link href={becHref(b)} onClick={() => setOpen(false)} className="block px-4 py-2.5 hover:bg-gray-800/50">
                      <p className="text-sm text-blue-300 truncate">{line.title}</p>
                      <p className="text-xs text-gray-500">{line.detail}</p>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {quiet ? (
            <Link href="/settings/connectors" onClick={() => setOpen(false)} data-testid="bell-quiet-tools" className="block px-4 py-2.5 border-t border-gray-800 hover:bg-gray-800/50">
              <p className="text-sm text-amber-300">{quiet.title}</p>
              <p className="text-xs text-gray-500">{quiet.detail}</p>
            </Link>
          ) : null}
          {approvals ? (
            <div data-testid="bell-approvals" className="px-4 py-2.5 border-t border-gray-800">
              <p className="text-sm text-amber-300">{approvals.title}</p>
              <p className="text-xs text-gray-500">{approvals.detail}</p>
            </div>
          ) : null}
          {billing && billing.lines > 0 ? (
            <Link href="/settings/billing" onClick={() => setOpen(false)} data-testid="bell-billing" className="block px-4 py-2.5 border-t border-gray-800 hover:bg-gray-800/50">
              <p className="text-sm text-amber-300">
                {billing.lines} billed line{billing.lines === 1 ? '' : 's'} off for {BILLING_DAYS}+ days
              </p>
              <p className="text-xs text-gray-500">
                across {billing.clients} client{billing.clients === 1 ? '' : 's'}; not accepted yet. Open Billed vs counted.
              </p>
            </Link>
          ) : null}
          <Link href="/alerts" onClick={() => setOpen(false)} className="block px-4 py-2.5 text-sm text-blue-400 hover:bg-gray-800/50 border-t border-gray-800 rounded-b-xl">
            View all alerts
          </Link>
        </div>
      ) : null}
    </div>
  );
}
