'use client';

/**
 * Reports > Executive digest > Scheduled reports: choose a report, who gets it, how often and when, and A.C.O.R.N e-mails it as plain text at that time (UTC). Each schedule shows when it last ran and what happened,
 * can be switched off, sent right now, or deleted. A report with nothing to say is not sent.
 */
import { useCallback, useEffect, useState } from 'react';

import { apiErrorDetail, reportSchedulesApi, type ReportScheduleList } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** When a schedule runs, in words (pure): "Every Monday at 07:00 UTC", "Every day at 07:00 UTC", "On day 5 of each month at 07:00 UTC". */
export function whenText(frequency: string, day: number, hour: number): string {
  const at = `${String(hour).padStart(2, '0')}:00 UTC`;
  if (frequency === 'daily') return `Every day at ${at}`;
  if (frequency === 'weekly') return `Every ${DAYS[day] ?? 'week'} at ${at}`;
  return `On day ${day} of each month at ${at}`;
}

export function ReportSchedules({ clientId = '' }: { clientId?: string }) {
  const [data, setData] = useState<ReportScheduleList | null>(null);
  const [problem, setProblem] = useState('');
  const [form, setForm] = useState({ name: '', kind: '', emails: '', frequency: 'weekly' as 'daily' | 'weekly' | 'monthly', day: 0, hour: 7 });

  const load = useCallback(async () => {
    try {
      const d = await reportSchedulesApi.list(clientId);
      setData(d);
      setForm((f) => (f.kind || d.kinds.length === 0 ? f : { ...f, kind: d.kinds[0]!.kind }));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not load the scheduled reports.');
    }
  }, [clientId]);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    setProblem('');
    try {
      await work();
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };

  if (!data) return problem ? <p className="text-sm text-amber-300">{problem}</p> : null;
  return (
    <section className="mt-8 space-y-3" data-testid="report-schedules">
      <h2 className="text-lg font-semibold text-white">Scheduled reports</h2>
      <p className="text-sm text-gray-400">Pick a report, who gets it and when; it is e-mailed as plain text (the mail account the compliance notice uses must be set up). A report with nothing to say is not sent.</p>
      {data.schedules.length === 0 ? (
        <p className="text-sm text-gray-500" data-testid="no-schedules">
          Nothing is scheduled yet.
        </p>
      ) : (
        <ul className="divide-y divide-gray-800 rounded border border-gray-800 text-sm">
          {data.schedules.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2" data-testid="schedule">
              <div>
                <p className="text-gray-100">
                  {s.name} <span className="text-xs text-gray-500">{s.report_label}{s.enabled ? '' : ' (off)'}</span>
                </p>
                <p className="text-xs text-gray-400">
                  {whenText(s.frequency, s.day, s.hour_utc)} to {s.emails.join(', ')}
                </p>
                <p className="text-xs text-gray-500">{s.last_run_at ? `Last run ${s.last_run_at.slice(0, 16).replace('T', ' ')} UTC: ` : ''}{s.last_result ?? 'Has not run yet.'}</p>
              </div>
              <span className="flex gap-2">
                <button type="button" className={btn} aria-label={`Send ${s.name} now`} onClick={() => void act(() => reportSchedulesApi.sendNow(clientId, s.id))}>
                  Send now
                </button>
                <button type="button" className={btn} aria-label={`${s.enabled ? 'Switch off' : 'Switch on'} ${s.name}`} onClick={() => void act(() => reportSchedulesApi.patch(clientId, s.id, { enabled: !s.enabled }))}>
                  {s.enabled ? 'Switch off' : 'Switch on'}
                </button>
                <button type="button" className={btn} aria-label={`Delete ${s.name}`} onClick={() => void act(() => reportSchedulesApi.remove(clientId, s.id))}>
                  Delete
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
            await reportSchedulesApi.create(clientId, {
              name: form.name.trim(),
              report_kind: form.kind,
              emails: form.emails.split(/[\s,;]+/).filter(Boolean),
              frequency: form.frequency,
              day: form.frequency === 'daily' ? 0 : form.frequency === 'weekly' ? form.day % 7 : Math.max(1, form.day),
              hour_utc: form.hour,
            });
            setForm((f) => ({ ...f, name: '', emails: '' }));
          });
        }}
      >
        <label className="text-xs text-gray-400">
          Name
          <input className={`${field} mt-1 block`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label className="text-xs text-gray-400">
          Report
          <select className={`${field} mt-1 block`} aria-label="Report" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {data.kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Send to (addresses)
          <input className={`${field} mt-1 block`} aria-label="Send to" value={form.emails} onChange={(e) => setForm({ ...form, emails: e.target.value })} />
        </label>
        <label className="text-xs text-gray-400">
          How often
          <select className={`${field} mt-1 block`} aria-label="How often" value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as 'daily' | 'weekly' | 'monthly', day: e.target.value === 'monthly' ? 1 : 0 })}>
            <option value="daily">Every day</option>
            <option value="weekly">Every week</option>
            <option value="monthly">Every month</option>
          </select>
        </label>
        {form.frequency === 'weekly' && (
          <label className="text-xs text-gray-400">
            On
            <select className={`${field} mt-1 block`} aria-label="Weekday" value={form.day} onChange={(e) => setForm({ ...form, day: Number(e.target.value) })}>
              {DAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        {form.frequency === 'monthly' && (
          <label className="text-xs text-gray-400">
            Day of month (1 to 28)
            <input type="number" min={1} max={28} className={`${field} mt-1 block w-20`} aria-label="Day of month" value={form.day} onChange={(e) => setForm({ ...form, day: Number(e.target.value) })} />
          </label>
        )}
        <label className="text-xs text-gray-400">
          Hour (UTC)
          <input type="number" min={0} max={23} className={`${field} mt-1 block w-20`} aria-label="Hour" value={form.hour} onChange={(e) => setForm({ ...form, hour: Number(e.target.value) })} />
        </label>
        <button type="submit" className={btn} disabled={form.name.trim().length < 2 || !form.kind || !form.emails.trim()}>
          Schedule it
        </button>
      </form>
      {problem && (
        <p role="alert" className="text-sm text-amber-300">
          {problem}
        </p>
      )}
    </section>
  );
}
