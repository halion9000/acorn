'use client';

/**
 * Metrics > Staff (the Rewst metric dashboards, rebuilt): Staff Metrics, Pods, Ticket Updates, DialPad, Staff Hours Distribution and the Service Desk Scorecard. Each is worked out by A.C.O.R.N from the weekly
 * facts CORE sends about once a day (HaloPSA time and tickets, Dialpad calls), never read live.
 */
import { useState } from 'react';

import { BarList, Cards, Columns, NothingYet, Page, Panel, Periods, Table, num, pctText, selectClass, useMetric, weekLabel } from './kit';

interface StaffMetricsData {
  received_at: string | null;
  weeks: { week: string; utilization: number | null; closed: number }[];
  members: { engineer: string; team: string; utilization: number | null; closed: number; labor_hours: number }[];
  teams: string[];
}

export function StaffMetricsView() {
  const [months, setMonths] = useState(3);
  const [team, setTeam] = useState('');
  const { data, denied, problem } = useMetric<StaffMetricsData>(`/api/v1/reports/metrics/staff-metrics?months=${months}${team ? `&team=${encodeURIComponent(team)}` : ''}`);
  return (
    <Page title="Staff metrics" subtitle="Weekly team metrics: utilization by week, tickets closed by week and utilization by team member." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Team
          <select aria-label="Team" className={selectClass} value={team} onChange={(e) => setTeam(e.target.value)}>
            <option value="">All teams</option>
            {(data?.teams ?? []).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <Periods value={months} onChange={setMonths} options={[1, 3, 6]} />
      </div>
      {data?.received_at && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Utilization % by week" testId="util-by-week">
            <Columns points={data.weeks.map((w) => ({ label: weekLabel(w.week), value: w.utilization }))} unit="%" />
          </Panel>
          <Panel title="Tickets closed by week" testId="closed-by-week">
            <Columns points={data.weeks.map((w) => ({ label: weekLabel(w.week), value: w.closed }))} />
          </Panel>
          <div className="lg:col-span-2" data-testid="util-by-member">
            <Table head={['Team member', 'Team', 'Utilization', 'Tickets closed', 'Labor hours']} rows={data.members.map((m) => [m.engineer, m.team || '—', pctText(m.utilization), num(m.closed), num(m.labor_hours, 1)])} />
          </div>
        </div>
      )}
    </Page>
  );
}

interface PodsData {
  received_at: string | null;
  weeks: string[];
  pods: { pod: string; engineers: number; utilization: number | null; resolved: number; created: number; days_off: number; holidays: number; weekly: { week: string; engineers: { engineer: string; utilization: number; resolved: number; created: number; days_off: number; holidays: number }[] }[] }[];
}

export function PodsView() {
  const [months, setMonths] = useState(3);
  const { data, denied, problem } = useMetric<PodsData>(`/api/v1/reports/metrics/pods?months=${months}`);
  return (
    <Page title="Metrics by pod" subtitle="Each pod's engineers, average utilization, tickets resolved and created, days off and holidays." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <Periods value={months} onChange={setMonths} options={[1, 3, 6, 12]} />
      {data?.received_at && (
        <>
          <Table
            testId="pods-table"
            head={['Pod', 'Engineers', 'Utilization', 'Resolved', 'Created', 'Days off', 'Holidays']}
            rows={data.pods.map((p) => [p.pod, num(p.engineers), pctText(p.utilization), num(p.resolved), num(p.created), num(p.days_off, 1), num(p.holidays, 1)])}
          />
          {data.pods.map((p) => (
            <details key={p.pod} className="rounded-lg border border-gray-800 p-3">
              <summary className="cursor-pointer text-sm text-gray-200">{p.pod}, week by week</summary>
              <div className="mt-2">
                <Table head={['Week', 'Engineer', 'Utilization', 'Resolved', 'Created', 'Days off']} firstWide rows={p.weekly.flatMap((w) => w.engineers.map((e) => [weekLabel(w.week), e.engineer, pctText(e.utilization), num(e.resolved), num(e.created), num(e.days_off, 1)]))} />
              </div>
            </details>
          ))}
        </>
      )}
    </Page>
  );
}

interface UpdatesData {
  received_at: string | null;
  weeks: string[];
  members: string[];
  rows: { engineer: string; total: number; by_week: Record<string, number> }[];
  weekly_total: Record<string, number>;
}

export function TicketUpdatesView() {
  const [months, setMonths] = useState(3);
  const [picked, setPicked] = useState<string[]>([]);
  const query = picked.map((m) => `&members=${encodeURIComponent(m)}`).join('');
  const { data, denied, problem } = useMetric<UpdatesData>(`/api/v1/reports/metrics/ticket-updates?months=${months}${query}`);
  const toggle = (m: string) => setPicked((p) => (p.includes(m) ? p.filter((x) => x !== m) : [...p, m]));
  return (
    <Page title="Ticket updates by team member" subtitle="How many times each team member updated a ticket, week by week." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <Periods value={months} onChange={setMonths} options={[1, 3, 6, 12]} />
      {data?.received_at && (
        <>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-300" aria-label="Members">
            <button type="button" className="text-blue-300 hover:underline" onClick={() => setPicked([])}>
              All
            </button>
            {data.members.map((m) => (
              <label key={m} className="flex items-center gap-1">
                <input type="checkbox" checked={picked.includes(m)} onChange={() => toggle(m)} /> {m}
              </label>
            ))}
          </fieldset>
          <Table
            testId="updates-table"
            head={['Team member', 'Total', ...data.weeks.map(weekLabel)]}
            rows={[...data.rows.map((r) => [r.engineer, num(r.total), ...data.weeks.map((w) => num(r.by_week[w] ?? 0))]), ['All shown', num(Object.values(data.weekly_total).reduce((a, b) => a + b, 0)), ...data.weeks.map((w) => num(data.weekly_total[w] ?? 0))]]}
          />
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

export function DialpadView() {
  const [months, setMonths] = useState(3);
  const [engineer, setEngineer] = useState('');
  const { data, denied, problem } = useMetric<DialpadData>(`/api/v1/reports/metrics/dialpad?months=${months}${engineer ? `&engineer=${encodeURIComponent(engineer)}` : ''}`);
  return (
    <Page title="DialPad metrics" subtitle="Calls and time on the phone, from Dialpad." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the Dialpad call facts" />}>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Engineer
          <select aria-label="Engineer" className={selectClass} value={engineer} onChange={(e) => setEngineer(e.target.value)}>
            <option value="">All engineers</option>
            {(data?.engineers ?? []).map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </label>
        <Periods value={months} onChange={setMonths} options={[1, 3, 6]} />
      </div>
      {data?.received_at && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Triage inbound by week" testId="triage-by-week">
            <Columns points={data.weeks.map((w) => ({ label: weekLabel(w.week), value: w.triage_inbound }))} />
          </Panel>
          <Panel title="Hours on call by week" testId="hours-by-week">
            <Columns points={data.weeks.map((w) => ({ label: weekLabel(w.week), value: w.hours_on_call }))} unit=" h" />
          </Panel>
          <div className="lg:col-span-2">
            <Table head={['Team member', 'Calls', 'Hours on call']} rows={data.people.map((p) => [p.engineer, num(p.calls), num(p.hours, 2)])} testId="calls-by-person" />
          </div>
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
  const [months, setMonths] = useState(3);
  const { data, denied, problem } = useMetric<HoursData>(`/api/v1/reports/metrics/staff-hours?months=${months}`);
  return (
    <Page title="Staff hours distribution" subtitle="Where each person's hours went, by ticket type. Hours only." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the HaloPSA hours" />}>
      <Periods value={months} onChange={setMonths} options={[1, 3, 6, 12]} />
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

export const gradeClass = (g: string): string => (g === 'S' || g === 'A' ? 'text-emerald-300' : g === 'B' ? 'text-sky-300' : g === 'C' ? 'text-amber-300' : g === '-' ? 'text-gray-500' : 'text-red-300');

export function ScorecardView() {
  const [months, setMonths] = useState(2);
  const [member, setMember] = useState('');
  const { data, denied, problem } = useMetric<ScoreData>(`/api/v1/reports/metrics/scorecard?months=${months}${member ? `&member=${encodeURIComponent(member)}` : ''}`);
  const d = data?.detail;
  return (
    <Page title="Service desk scorecard" subtitle="A score from 1 to 5 each week from tickets closed and updated, labor hours, calls, call time, customer satisfaction and utilization, weighted, with a grade." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the weekly staff facts" />}>
      <Periods value={months} onChange={setMonths} options={[1, 2, 3, 6, 12]} />
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
                <Panel title="Weekly score trend" testId="score-trend">
                  <Columns points={d.trend.map((t) => ({ label: weekLabel(t.week), value: t.score }))} />
                </Panel>
                <Table
                  testId="score-weeks"
                  head={['Week', ...data.metrics, 'Score', 'Grade']}
                  rows={[
                    ...d.weeks.map((w) => [`${weekLabel(w.week)}${w.score === null ? ' (not scored)' : ''}`, ...data.metrics.map((m) => (w.factors[m] === null || w.factors[m] === undefined ? '-' : String(w.factors[m]))), w.score === null ? '-' : String(w.score), w.grade]),
                    ['Average', ...data.metrics.map((m) => (d.metric_averages[m] === null || d.metric_averages[m] === undefined ? '-' : String(d.metric_averages[m]))), String(d.average ?? '-'), d.grade],
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

