'use client';

/**
 * Metrics > Staff (the Rewst metric dashboards, rebuilt): Staff Metrics, Pods, Ticket Updates, DialPad, Staff Hours Distribution and the Service Desk Scorecard. Each is worked out by A.C.O.R.N from the weekly
 * facts CORE sends about once a day (HaloPSA time and tickets, Dialpad calls), never read live.
 */
import Link from 'next/link';
import { Fragment, useState } from 'react';
import { AreaChart } from './AreaChart';
import { PodsMatrix, type PodRow } from './PodsMatrix';
import { UtilBars, UtilMatrix } from './UtilCharts';
import { RefreshMetrics } from './RefreshMetrics';
import { UpdatesMatrix, type UpdateDetail } from './UpdatesMatrix';
import { MetricPicker } from './MetricPicker';

import { BarList, Cards, Columns, NothingYet, Page, Panel, PeriodPicker, Table, num, pctText, selectClass, useMetric, usePeriod, weekLabel } from './kit';

interface StaffMetricsData {
  received_at: string | null;
  weeks: { week: string; utilization: number | null; closed: number }[];
  members: { engineer: string; team: string; utilization: number | null; closed: number; labor_hours: number; by_week?: Record<string, number | null> }[];
  teams: string[];
}

export function StaffMetricsView() {
  const period = usePeriod(3);
  const [team, setTeam] = useState('');
  const { data, denied, problem, reload } = useMetric<StaffMetricsData>(`/api/v1/reports/metrics/staff-metrics?${period.query}${team ? `&team=${encodeURIComponent(team)}` : ''}`);
  return (
    <Page title="Weekly Team Metrics" subtitle="Utilization (hours logged over hours available) and tickets closed, by week and by team member." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <div className="flex flex-wrap items-center gap-3">
        <PeriodPicker period={period} options={[1, 3, 6]} />
        <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Team
          <select aria-label="Team" className={selectClass} value={team} onChange={(e) => setTeam(e.target.value)}>
            <option value="">All Teams</option>
            {(data?.teams ?? []).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>
      {data?.received_at && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Utilization % by Week" testId="util-by-week">
              <UtilBars points={data.weeks.map((w) => ({ label: w.week, value: w.utilization }))} />
            </Panel>
            <Panel title="Tickets Closed by Week" testId="closed-by-week">
              <AreaChart points={data.weeks.map((w) => ({ label: w.week, value: w.closed }))} color="#00d4ff" testId="chart-closed" />
            </Panel>
          </div>
          <Panel title="Utilization By Team Member" testId="util-by-member">
            <UtilMatrix weeks={data.weeks.map((w) => w.week)} rows={data.members.map((m) => ({ name: m.engineer, by_week: m.by_week ?? {} }))} />
          </Panel>
        </div>
      )}
    </Page>
  );
}

interface PodsData {
  received_at: string | null;
  weeks: string[];
  rows?: PodRow[];
  pods: { pod: string; engineers: number; utilization: number | null; resolved: number; created: number; days_off: number; holidays: number; weekly: { week: string; engineers: { engineer: string; utilization: number; resolved: number; created: number; days_off: number; holidays: number }[] }[] }[];
}

export function PodsView() {
  const period = usePeriod(3);
  const { data, denied, problem, reload } = useMetric<PodsData>(`/api/v1/reports/metrics/pods?${period.query}`);
  return (
    <Page title="Metrics by Pods" subtitle="Each pod and its engineers, week by week and by month: tickets resolved and created, available and logged hours, and utilization." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <PeriodPicker period={period} options={[1, 3, 6, 12]} />
      <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
      {data?.received_at && (
        <Panel title="Metrics by Pod" testId="pods-table">
          <PodsMatrix rows={data.rows ?? []} weeks={data.weeks} />
        </Panel>
      )}
    </Page>
  );
}

interface UpdatesData {
  received_at: string | null;
  weeks: string[];
  members: string[];
  rows: { engineer: string; total: number; by_week: Record<string, number>; detail?: Record<string, UpdateDetail> }[];
  weekly_total: Record<string, number>;
}

export function TicketUpdatesView() {
  const period = usePeriod(3);
  // null: every member; a list: only those (an empty list shows none).
  const [picked, setPicked] = useState<string[] | null>(null);
  const query = (picked ?? []).map((m) => `&members=${encodeURIComponent(m)}`).join('');
  const { data, denied, problem, reload } = useMetric<UpdatesData>(`/api/v1/reports/metrics/ticket-updates?${period.query}${query}`);
  return (
    <Page title="Ticket Updates by Team Member" subtitle="How many different tickets each team member logged time on, week by week. HaloPSA cannot list every note or update in bulk, so an update with no logged time is not counted." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <PeriodPicker period={period} options={[1, 3, 6, 12]} />
      <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
      {data?.received_at && (
        <>
          <MetricPicker
            noun="team members"
            options={data.members.map((m) => ({ value: m, label: m }))}
            selected={picked ?? data.members}
            onChange={(next) => setPicked(next.length === data.members.length ? null : next)}
          />
          {data.rows.every((r) => r.total === 0) && (
            <p className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200" data-testid="updates-all-zero">
              Every count here is zero. CORE reads these from HaloPSA's ticket actions about once a day; if they stay zero, HaloPSA is not returning the actions or not saying who made them. CORE's log says which.
            </p>
          )}
          <Panel title="Ticket Updates by Team Member" testId="updates-table">
            <UpdatesMatrix weeks={data.weeks} rows={data.rows} />
          </Panel>
        </>
      )}
    </Page>
  );
}

interface DialpadData {
  received_at: string | null;
  weeks: { week: string; triage_inbound: number; hours_on_call: number; calls: number }[];
  people: { engineer: string; calls: number; hours: number; by_week: Record<string, { calls: number; hours: number }> }[];
  engineers: string[];
}

const WEEK_CELL = 'px-3 py-2 text-center tabular-nums';

/** One row of the calls and hours table: the person's calls and hours in each week (zero when the week has none). */
export function dialpadCells(by_week: DialpadData['people'][number]['by_week'], weeks: string[]): { calls: number; hours: number }[] {
  return weeks.map((w) => by_week[w] ?? { calls: 0, hours: 0 });
}

export function DialpadView() {
  const period = usePeriod(3);
  const [engineer, setEngineer] = useState('');
  const { data, denied, problem, reload } = useMetric<DialpadData>(`/api/v1/reports/metrics/dialpad?${period.query}${engineer ? `&engineer=${encodeURIComponent(engineer)}` : ''}`);
  const weeks = (data?.weeks ?? []).map((w) => w.week);
  const triage = (data?.weeks ?? []).some((w) => w.triage_inbound > 0);
  const who = engineer || 'All Teams';
  const people = [...(data?.people ?? [])].sort((a, b) => a.engineer.localeCompare(b.engineer));
  return (
    <Page title="DialPad Metrics" subtitle="Calls and time on the phone, from Dialpad." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the Dialpad call facts" />}>
      <div className="flex flex-wrap items-center gap-3">
        <PeriodPicker period={period} options={[1, 3, 6]} />
        <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Engineer
          <select aria-label="Engineer" className={selectClass} value={engineer} onChange={(e) => setEngineer(e.target.value)}>
            <option value="">All Teams</option>
            {(data?.engineers ?? []).map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </label>
      </div>
      {data?.received_at && (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title={`${who} ${triage ? 'Triage Inbound' : 'Calls'} By Week`} testId="triage-by-week">
              <AreaChart points={data.weeks.map((w) => ({ label: w.week, value: triage ? w.triage_inbound : w.calls }))} color="#8b5cf6" testId="chart-inbound" />
            </Panel>
            <Panel title={`${who} Hours On Call By Week`} testId="hours-by-week">
              <AreaChart points={data.weeks.map((w) => ({ label: w.week, value: w.hours_on_call }))} color="#06b6d4" testId="chart-hours" />
            </Panel>
          </div>
          <Panel title="Call Count and Hours on Call by Week and Team Member" testId="calls-by-person">
            <div className="max-h-[32rem] overflow-auto">
              <table className="w-full min-w-max border-collapse text-sm">
                <thead className="sticky top-0 z-10" style={{ background: 'var(--metrics-head, #1f2f33)' }}>
                  <tr>
                    <th rowSpan={2} className="sticky left-0 px-4 py-2 text-center font-semibold" style={{ background: 'inherit' }}>
                      Engineer
                    </th>
                    {weeks.map((w) => (
                      <th key={w} colSpan={2} className="border-l border-gray-700 px-3 py-2 text-center font-semibold">
                        {w}
                      </th>
                    ))}
                  </tr>
                  <tr>
                    {weeks.map((w) => (
                      <Fragment key={w}>
                        <th className="border-l border-gray-700 px-3 py-1.5 text-center text-xs font-semibold">{'# of Calls'}</th>
                        <th className="px-3 py-1.5 text-center text-xs font-semibold">Hours</th>
                      </Fragment>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {people.map((p, n) => (
                    <tr key={p.engineer} style={n % 2 === 1 ? { background: 'rgba(255,255,255,0.04)' } : undefined}>
                      <td className="sticky left-0 whitespace-nowrap px-4 py-2 text-center font-semibold" style={{ background: n % 2 === 1 ? '#2a3a3e' : '#243236' }}>
                        {p.engineer}
                      </td>
                      {dialpadCells(p.by_week, weeks).map((c, i) => (
                        <Fragment key={weeks[i]}>
                          <td className={`${WEEK_CELL} border-l border-gray-800`}>{c.calls}</td>
                          <td className={WEEK_CELL}>{c.hours.toFixed(2)}</td>
                        </Fragment>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </Page>
  );
}

interface HoursData {
  received_at: string | null;
  total_hours: number;
  types: { type: string; hours: number; share_percent: number | null }[];
  people: { name: string; total: number; by_type: Record<string, number> }[];
}

export function StaffHoursView() {
  const period = usePeriod(3);
  const { data, denied, problem, reload } = useMetric<HoursData>(`/api/v1/reports/metrics/staff-hours?${period.query}`);
  return (
    <Page title="Staff hours distribution" subtitle="Where each person's hours went, by ticket type. Hours only." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the HaloPSA hours" />}>
      <PeriodPicker period={period} options={[1, 3, 6, 12]} />
      <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
      {data?.received_at && (
        <>
          <Cards items={[['Hours worked', `${num(data.total_hours, 1)} h`], ['People', String(data.people.length)], ['Ticket types', String(data.types.length)]]} />
          <Panel title="By ticket type" testId="hours-by-type">
            <BarList rows={data.types.map((t) => ({ label: t.type, value: t.hours, text: `${num(t.hours, 1)} h${t.share_percent !== null ? ` (${t.share_percent}%)` : ''}` }))} />
          </Panel>
          <Table testId="hours-by-person" head={['Person', 'Total', ...data.types.map((t) => t.type)]} rows={data.people.map((p) => [p.name, num(p.total, 1), ...data.types.map((t) => num(p.by_type[t.type] ?? 0, 1))])} />
        </>
      )}
    </Page>
  );
}

interface ScoreData {
  received_at: string | null;
  metrics: string[];
  weights: Record<string, number>;
  people: { engineer: string; team: string; weeks_scored: number; average: number | null; grade: string }[];
  detail: {
    engineer: string;
    average: number | null;
    grade: string;
    weeks: { week: string; score: number | null; grade: string; factors: Record<string, number | null>; values: Record<string, number | null>; days_worked: number }[];
    metric_averages: Record<string, number | null>;
    trend: { week: string; score: number | null }[];
  } | null;
}

/** The metrics to show: all of them until a person unticks some (``picked`` is null while every one is shown). */
export const shownMetrics = (all: string[], picked: string[] | null): string[] => (picked === null ? all : all.filter((m) => picked.includes(m)));

/** The picked list after one metric is ticked or unticked; null again when every metric is on. */
export function toggleMetric(all: string[], picked: string[] | null, metric: string): string[] | null {
  const now = shownMetrics(all, picked);
  const next = now.includes(metric) ? now.filter((m) => m !== metric) : all.filter((m) => now.includes(m) || m === metric);
  return next.length === all.length ? null : next;
}

/** One metric's 1 to 5 score per week as small bars with the score above each; a week not scored is empty. */
export function ScoreBars({ points }: { points: { label: string; value: number | null }[] }) {
  return (
    <div data-testid="score-bars">
      <div className="flex items-end gap-1.5" style={{ height: 90 }}>
        {points.map((p) => (
          <div key={p.label} className="flex flex-1 flex-col items-center justify-end" style={{ height: '100%' }}>
            <span className="text-[10px] tabular-nums">{p.value ?? ''}</span>
            <div className="w-full rounded-t" style={{ height: `${((p.value ?? 0) / 5) * 100}%`, background: 'rgba(0,212,255,0.55)', border: '1px solid #00d4ff' }} />
          </div>
        ))}
      </div>
      <div className="mt-0.5 flex gap-1.5 text-[10px]" style={{ color: 'var(--metrics-soft)' }}>
        {points.map((p) => (
          <span key={p.label} className="flex-1 text-center">
            {weekLabel(p.label)}
          </span>
        ))}
      </div>
    </div>
  );
}

export const gradeClass = (g: string): string => (g === 'S' || g === 'A' ? 'text-emerald-300' : g === 'B' ? 'text-sky-300' : g === 'C' ? 'text-amber-300' : g === '-' ? 'text-gray-500' : 'text-red-300');

export function ScorecardView() {
  const period = usePeriod(2);
  const [member, setMember] = useState('');
  const [picked, setPicked] = useState<string[] | null>(null);
  const { data, denied, problem, reload } = useMetric<ScoreData>(`/api/v1/reports/metrics/scorecard?${period.query}${member ? `&member=${encodeURIComponent(member)}` : ''}`);
  const d = data?.detail;
  return (
    <Page title="Service desk scorecard" subtitle="A score from 1 to 5 each week from tickets closed and updated, labor hours, calls, call time, customer satisfaction and utilization, weighted, with a grade." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <div className="flex flex-wrap items-center gap-3">
        <PeriodPicker period={period} options={[1, 2, 3, 6, 12]} />
        <RefreshMetrics receivedAt={(data as { received_at?: string | null } | null)?.received_at} reload={reload} />
        <Link href="/settings/scorecard" className="text-sm text-blue-300 underline">
          Scorecard settings (weights and brackets)
        </Link>
        <Link href="/settings/metrics-people" className="text-sm text-blue-300 underline">
          Leave people out of the metrics
        </Link>
      </div>
      {data?.received_at && (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Panel title="Team member" testId="score-people">
            <ul className="space-y-1">
              {data.people.map((p) => (
                <li key={p.engineer}>
                  <label className="flex cursor-pointer items-center justify-between gap-2 text-sm text-gray-200">
                    <span className="flex items-center gap-2">
                      <input type="radio" name="member" aria-label={p.engineer} checked={member === p.engineer} onChange={() => setMember(p.engineer)} />
                      {p.engineer}
                    </span>
                    <span className={`tabular-nums ${gradeClass(p.grade)}`}>
                      {p.average ?? '—'} {p.grade}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </Panel>
          <div className="space-y-4">
            {!d && <p className="text-sm text-gray-400">Choose a team member to see their weeks.</p>}
            {d && (
              <>
                <Cards items={[['Average score', String(d.average ?? '—')], ['Grade', d.grade], ['Weeks', String(d.weeks.length)]]} />
                <Panel title="Weekly Score Trend" testId="score-trend">
                  <AreaChart points={d.trend.map((t) => ({ label: t.week, value: t.score ?? 0 }))} color="#00d4ff" testId="score-trend-chart" />
                </Panel>
                <Panel title="Select Metric(s)" testId="score-metric-picker">
                  <div className="flex flex-wrap gap-3 text-sm">
                    {data.metrics.map((m) => (
                      <label key={m} className="flex items-center gap-1.5">
                        <input type="checkbox" aria-label={`Show ${m}`} checked={shownMetrics(data.metrics, picked).includes(m)} onChange={() => setPicked(toggleMetric(data.metrics, picked, m))} />
                        {m}
                      </label>
                    ))}
                  </div>
                </Panel>
                <Panel title="Metrics Trend by Week" testId="score-metric-trends">
                  <div className="space-y-3">
                    {shownMetrics(data.metrics, picked).map((m) => (
                      <div key={m}>
                        <p className="mb-1 text-xs font-semibold">
                          {m} <span className="font-normal text-gray-400">(weight {data.weights[m]})</span>
                        </p>
                        <ScoreBars points={[...d.weeks].reverse().map((w) => ({ label: w.week, value: w.factors[m] ?? null }))} />
                      </div>
                    ))}
                  </div>
                </Panel>
                <Table
                  testId="score-weeks"
                  head={['Week', ...shownMetrics(data.metrics, picked), 'Score', 'Grade']}
                  rows={[
                    ...d.weeks.map((w) => [`${weekLabel(w.week)}${w.score === null ? ' (not scored)' : ''}`, ...shownMetrics(data.metrics, picked).map((m) => (w.factors[m] === null || w.factors[m] === undefined ? '-' : String(w.factors[m]))), w.score === null ? '-' : String(w.score), w.grade]),
                    ['Average', ...shownMetrics(data.metrics, picked).map((m) => (d.metric_averages[m] === null || d.metric_averages[m] === undefined ? '-' : String(d.metric_averages[m]))), String(d.average ?? '-'), d.grade],
                  ]}
                />
                <p className="text-xs text-gray-500">Weights: {data.metrics.map((m) => `${m} ${data.weights[m]}`).join(', ')}. A week with no activity or a whole week off is not scored.</p>
              </>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}

