'use client';

/**
 * The small set of pieces every page is built from (design system, Phase 1): PageHeader, StatCard with an optional sparkline, Sparkline, BarCell (a number with a bar behind it), Segmented (one choice from a few),
 * Skeleton and EmptyState. They use the theme tokens and the re-pointed gray scale, so they look right in light and dark; numbers use tabular figures; change is shown with an arrow AND a word, never color alone.
 * Shown together on one page for review: /guide/ui.
 */
import { useId, type ReactNode } from 'react';

import { deltaTone, formatDelta, type Tone } from './format';

const cx = (...parts: (string | false | null | undefined)[]): string => parts.filter(Boolean).join(' ');

export const toneText: Record<Tone, string> = {
  good: 'text-emerald-400',
  bad: 'text-red-400',
  neutral: 'text-gray-400',
};
const toneFill: Record<Tone, string> = {
  good: 'bg-emerald-500',
  bad: 'bg-red-500',
  neutral: 'bg-blue-500',
};

/** The top of every page: a title, one line under it, actions at the right, and "About this page" that opens the longer explanation instead of printing it. */
export function PageHeader({ title, subtitle, actions, about }: { title: string; subtitle?: string; actions?: ReactNode; about?: ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3" data-testid="page-header">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-gray-400">{subtitle}</p>}
        {about && (
          <details className="mt-2 text-sm text-gray-400">
            <summary className="cursor-pointer text-blue-300 hover:underline">About this page</summary>
            <div className="mt-2 max-w-3xl space-y-2">{about}</div>
          </details>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A line of values as a small chart, scaled to its own range. Needs two points or more; draws nothing otherwise. */
export function Sparkline({ values, tone = 'neutral', label }: { values: number[]; tone?: Tone; label?: string }) {
  const id = useId();
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 80;
  const h = 24;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`);
  const stroke = tone === 'good' ? '#10b981' : tone === 'bad' ? '#ef4444' : '#3b82f6';
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={label ?? `Trend over ${values.length} points`} aria-describedby={id} className="shrink-0">
      <desc id={id}>{`From ${values[0]} to ${values[values.length - 1]}`}</desc>
      <polyline points={pts.join(' ')} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** A big number with its label, the change since the last period (arrow, sign and word), a note, and an optional sparkline. ``onClick`` makes the whole card a button. */
export function StatCard({
  label,
  value,
  delta,
  upIsGood = true,
  note,
  spark,
  onClick,
  loading,
}: {
  label: string;
  value: ReactNode;
  delta?: number | null;
  upIsGood?: boolean;
  note?: string;
  spark?: number[];
  onClick?: () => void;
  loading?: boolean;
}) {
  const tone = deltaTone(delta, upIsGood);
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-gray-400">{label}</p>
        {spark && !loading && <Sparkline values={spark} tone={tone} />}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-24" />
      ) : (
        <p className="mt-1 text-3xl font-semibold tabular-nums tracking-tight text-white" data-testid="stat-value">
          {value}
        </p>
      )}
      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-gray-400">
        {delta !== undefined && delta !== null && !loading && (
          <span className={cx('inline-flex items-center gap-1 font-medium tabular-nums', toneText[tone])} data-testid="stat-delta">
            <span aria-hidden="true">{delta > 0 ? '▲' : delta < 0 ? '▼' : '▬'}</span>
            {formatDelta(delta)}
            <span className="sr-only">{tone === 'good' ? ' (better)' : tone === 'bad' ? ' (worse)' : ''}</span>
          </span>
        )}
        {note && <span>{note}</span>}
      </p>
    </>
  );
  const base = 'rounded-xl border border-gray-800 bg-gray-900 p-4 text-left';
  return onClick ? (
    <button type="button" onClick={onClick} className={cx(base, 'transition hover:border-gray-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500')}>
      {body}
    </button>
  ) : (
    <div className={base}>{body}</div>
  );
}

/** A number with a bar behind it, as a share of ``max``: a margin, a count against the largest, a difference. */
export function BarCell({ value, max, text, tone = 'neutral' }: { value: number | null; max: number; text: string; tone?: Tone }) {
  const pct = value === null || max <= 0 ? 0 : Math.max(0, Math.min(100, (Math.abs(value) / max) * 100));
  return (
    <span className="relative inline-block min-w-[5.5rem] text-right tabular-nums" data-testid="bar-cell">
      <span aria-hidden="true" className={cx('absolute inset-y-0 right-0 rounded-sm opacity-20', toneFill[tone])} style={{ width: `${pct}%` }} />
      <span className="relative px-1">{text}</span>
    </span>
  );
}

/** One choice from a few (periods, views): a connected row of buttons, the chosen one filled. Replaces rows of loose pill buttons. */
export function Segmented<T extends string | number>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-lg border border-gray-700 bg-gray-900">
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            'px-3 py-1.5 text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500',
            i > 0 && 'border-l border-gray-700',
            o.value === value ? 'bg-blue-600 font-medium text-white' : 'text-gray-300 hover:bg-gray-800',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A grey block that stands in for content while it loads, so a slow read looks like waiting and not like "no data". */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx('animate-pulse rounded-md bg-gray-800', className)} data-testid="skeleton" />;
}

/** Rows of skeleton for a table that is loading. */
export function SkeletonRows({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-2">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton key={c} className={cx('h-5', c === 0 ? 'w-1/4' : 'flex-1')} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** What a page or panel says when there is nothing to show: one sentence about why, and one thing to do about it. */
export function EmptyState({ title, why, action }: { title: string; why?: string; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-700 p-8 text-center" data-testid="empty-state">
      <p className="text-base font-medium text-white">{title}</p>
      {why && <p className="mx-auto mt-1 max-w-md text-sm text-gray-400">{why}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
