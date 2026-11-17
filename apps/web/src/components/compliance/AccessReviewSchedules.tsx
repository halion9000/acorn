'use client';

/**
 * Access reviews that start themselves: one schedule per system (every 90 days is a quarter). When a schedule comes due, A.C.O.R.N takes a fresh snapshot of the system's people and opens a review with the chosen
 * reviewer, due 30 days later. Backed by /api/v1/compliance/access-reviews/schedules.
 */
import { useCallback, useEffect, useState } from 'react';

import { accessReviewsApi, apiErrorDetail, type AccessReviewSchedule } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';

/** "every quarter", "every 30 days" (pure). */
export function everyText(days: number): string {
  return days === 90 ? 'every quarter' : days === 365 ? 'every year' : `every ${days} days`;
}

/** One line for a schedule: what it does, when the next starts, and why the last attempt started nothing (pure). */
export function scheduleLine(s: AccessReviewSchedule): string {
  const when = s.enabled ? `next starts ${s.next_start}` : 'switched off';
  return `${s.system} ${everyText(s.every_days)}, ${when}${s.reviewer ? `, reviewer ${s.reviewer}` : ''}`;
}

export function AccessReviewSchedules({ clientId, systems }: { clientId: string; systems: string[] }) {
  const [rows, setRows] = useState<AccessReviewSchedule[] | null>(null);
  const [system, setSystem] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [days, setDays] = useState(90);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try {
      setRows(await accessReviewsApi.schedules(clientId));
    } catch {
      setRows(null);
    }
  }, [clientId]);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    setErr('');
    try {
      await work();
      await load();
    } catch (e) {
      setErr(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };

  if (rows === null) return null;
  return (
    <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="review-schedules">
      <h2 className="text-sm font-semibold text-white">Starts by itself</h2>
      <p className="text-xs text-gray-400">A review of a system can start on its own every quarter: a fresh snapshot of who has access, due 30 days after it starts.</p>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {rows.length > 0 && (
        <ul className="divide-y divide-gray-800 text-sm" aria-label="Repeating reviews">
          {rows.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span className="text-gray-200">
                {scheduleLine(s)}
                {s.last_error && <span className="block text-xs text-amber-300">The last try started nothing: {s.last_error}</span>}
              </span>
              <span className="flex gap-2">
                <button type="button" className={btn} onClick={() => void act(() => accessReviewsApi.saveSchedule(clientId, { system: s.system, reviewer: s.reviewer, every_days: s.every_days, enabled: !s.enabled }))}>
                  {s.enabled ? 'Switch off' : 'Switch on'}
                </button>
                <button type="button" className={btn} aria-label={`Remove the repeat for ${s.system}`} onClick={() => void act(() => accessReviewsApi.removeSchedule(clientId, s.id))}>
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            await accessReviewsApi.saveSchedule(clientId, { system: system.trim(), reviewer: reviewer.trim() || null, every_days: days, enabled: true });
            setSystem('');
          });
        }}
      >
        <label className="text-xs text-gray-400">
          System
          <input aria-label="System to repeat" required list="schedule-systems" value={system} onChange={(e) => setSystem(e.target.value)} className={`${field} mt-1 block w-48`} />
          <datalist id="schedule-systems">
            {systems.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </label>
        <label className="text-xs text-gray-400">
          Reviewer
          <input aria-label="Reviewer of the repeat" value={reviewer} onChange={(e) => setReviewer(e.target.value)} className={`${field} mt-1 block w-48`} />
        </label>
        <label className="text-xs text-gray-400">
          Every (days)
          <input aria-label="Days between reviews" type="number" min={7} max={400} value={days} onChange={(e) => setDays(Math.max(7, Math.min(400, Number(e.target.value) || 90)))} className={`${field} mt-1 block w-24`} />
        </label>
        <button type="submit" className={btn} disabled={!system.trim()}>
          Repeat this review
        </button>
      </form>
    </section>
  );
}
