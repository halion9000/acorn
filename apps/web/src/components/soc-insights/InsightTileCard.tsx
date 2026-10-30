/**
 * Single tile on the SOC Insights dashboard (T3.1).
 *
 * Pure presentational — takes the typed payload from the aggregator
 * endpoint and renders value + delta + sparkline. All formatting is
 * keyed off the tile's ``unit`` so a future tile can ship by adding
 * a new branch here instead of teaching every consumer about a new
 * unit.
 */
'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';

import type { InsightTile } from '@/lib/api';

interface InsightTileCardProps {
  tile: InsightTile;
  sparkline: ReactNode;
  /** The client these numbers are for (the alerts link then lists only that client's alerts). */
  clientId?: string;
}

/** The page that lists what is behind a tile, or null when there is none. The alerts pages take the client as ``client``. */
export function tileHref(key: string, clientId?: string): string | null {
  const alerts = (status: string): string => `/alerts?status=${status}${clientId ? `&client=${encodeURIComponent(clientId)}` : ''}`;
  switch (key) {
    case 'mtta':
    case 'alerts_per_day':
      return alerts('all');
    case 'mttr':
      return alerts('resolved');
    case 'fp_rate':
      return alerts('false_positive');
    case 'cases_per_day':
    case 'analyst_hours_saved':
      return '/cases';
    case 'open_alerts':
    case 'sla_breaches':
      return alerts('open');
    case 'noisy_alert_types':
    case 'noisiest_clients':
      return '/noise-tuning';
    case 'unusual_signins':
      return '/settings/signin-scores';
    case 'silent_sources':
      return '/settings/platform-health';
    case 'leaked_credentials':
    case 'google_admins_without_2step':
    case 'google_failed_sign_ins':
      return '/settings/fleet-posture';
    case 'playbook_coverage':
      return '/playbooks';
    case 'ticket_linkage':
      return alerts('all');
    case 'agent_cost_per_investigation':
      return '/costs';
    default:
      return null;
  }
}

export function InsightTileCard({ tile, sparkline, clientId }: InsightTileCardProps) {
  const href = tileHref(tile.key, clientId);
  const direction = deltaDirection(tile);
  const deltaLabel = formatDelta(tile.delta_pct);
  const deltaTitle =
    tile.delta_pct === null
      ? 'No change figure yet: there is not a full earlier window of data to compare with.'
      : `Compared to the previous window: ${deltaLabel}.`;

  const card = (
    <div
      className={`flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4${href ? ' transition-colors hover:border-primary/50' : ''}`}
      // The `aria-label` rolls the value + delta into one string so a
      // screen reader announces the change without us shipping a
      // table-with-headers.
      aria-label={`${tile.label}: ${formatValue(tile)}, ${deltaTitle}${tile.detail ? ` ${tile.detail}.` : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {tile.label}
        </span>
        <span
          className={
            direction === 'up'
              ? 'rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300'
              : direction === 'down'
                ? 'rounded-full bg-rose-500/10 px-2 py-0.5 text-xs font-medium text-rose-700 dark:text-rose-300'
                : 'rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground'
          }
          title={deltaTitle}
        >
          {deltaLabel}
        </span>
      </div>

      <div className="mt-2 flex items-end justify-between gap-2">
        <span className="text-2xl font-semibold tabular-nums">{formatValue(tile)}</span>
        <div className="text-muted-foreground">{sparkline}</div>
      </div>
      {tile.detail ? (
        <p className="mt-2 text-xs text-muted-foreground" data-testid={`tile-detail-${tile.key}`}>
          {tile.detail}
        </p>
      ) : null}
      {tile.items && tile.items.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-xs" data-testid={`tile-items-${tile.key}`}>
          {tile.items.map((item) => (
            <li key={item.label} className="flex justify-between gap-2">
              <span className="truncate text-foreground" title={item.label}>
                {item.label}
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{item.display}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
  if (!href) return card;
  return (
    <Link href={href} title={`See what is behind ${tile.label}`} className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
      {card}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatValue(tile: InsightTile): string {
  // Nothing to measure: a dash, never a 0.0h or 0% that reads as a good result.
  if (tile.has_data === false) return '—';
  switch (tile.unit) {
    case 'hours':
      return `${tile.value.toFixed(1)}h`;
    case 'hours_saved':
      // Round whole hours — fractional analyst hours are noise at the
      // dashboard level. The headline number is the talking-point.
      return `${Math.round(tile.value)}h`;
    case 'pct':
      // Server emits 0–1; render as percentage.
      return `${(tile.value * 100).toFixed(1)}%`;
    case 'usd':
      return tile.value < 1
        ? `$${tile.value.toFixed(3)}`
        : `$${tile.value.toFixed(2)}`;
    case 'count':
    default:
      return Number.isInteger(tile.value)
        ? tile.value.toString()
        : tile.value.toFixed(1);
  }
}

function formatDelta(delta: number | null): string {
  if (delta === null) return '—';
  const sign = delta > 0 ? '+' : '';
  return `${sign}${delta.toFixed(1)}%`;
}

/**
 * Classify the delta into a UX direction.
 *
 * Note: for tiles where "more = worse" (MTTA, MTTR, FP rate, cost,
 * alerts/day) a positive delta should *not* be celebrated. We push
 * those into ``down`` (red) so the colour matches the operator's
 * intuition. ``hours_saved`` and ``cases_per_day`` flip the polarity.
 */
function deltaDirection(tile: InsightTile): 'up' | 'down' | 'flat' {
  if (tile.delta_pct === null || tile.delta_pct === 0) return 'flat';
  const positive = tile.delta_pct > 0;
  const goodWhenUp = ['analyst_hours_saved', 'automation_rate', 'playbook_coverage', 'ticket_linkage'].includes(tile.key);
  return positive === goodWhenUp ? 'up' : 'down';
}
