'use client';

/**
 * Metrics > Meetings (the Rewst Meetings page, rebuilt): hours spent in meetings, from each engineer's Microsoft 365 calendar (CORE reads them through CIPP about once a day). Total meeting hours by week,
 * meeting hours by team member and by week, and the total for each team, for all teams or one.
 */
import { useState } from 'react';

import { AreaChart } from './AreaChart';
import { NothingYet, Page, Panel, PeriodPicker, Table, num, selectClass, useMetric, usePeriod } from './kit';

interface MeetingsData {
  received_at: string | null;
  weeks: string[];
  total_hours: number;
  by_week: { week: string; hours: number }[];
  people: { engineer: string; team: string; total: number; by_week: Record<string, number> }[];
  by_team: { team: string; hours: number }[];
  teams: string[];
}

export function MeetingsView() {
  const period = usePeriod(3);
  const [team, setTeam] = useState('');
  const { data, denied, problem } = useMetric<MeetingsData>(`/api/v1/reports/metrics/meetings?${period.query}${team ? `&team=${encodeURIComponent(team)}` : ''}`);
  return (
    <Page title="Meetings" subtitle="Hours in meetings, from each engineer's Microsoft 365 calendar: cancelled, all-day and free time are not counted." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={<NothingYet show={data?.received_at === null} what="the meeting hours" />}>
      <div className="flex flex-wrap items-center gap-3">
        <PeriodPicker period={period} options={[1, 3, 6]} />
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
          <Panel title={`Total meeting hours: ${num(data.total_hours, 1)}`} testId="meetings-total">
            <AreaChart points={data.by_week.map((w) => ({ label: w.week, value: w.hours }))} color="#00d4ff" testId="meetings-chart" />
          </Panel>
          <Panel title="Meeting hours by Team Member" testId="meetings-people">
            <Table head={['User Name', 'Team', 'Total', ...data.weeks]} rows={data.people.map((p) => [p.engineer, p.team, num(p.total, 2), ...data.weeks.map((w) => num(p.by_week[w] ?? 0, 2))])} />
          </Panel>
          <Panel title="Total meeting hours by Team" testId="meetings-teams">
            <Table head={['Team', 'Hours']} rows={data.by_team.map((t) => [t.team, num(t.hours, 2)])} />
          </Panel>
        </div>
      )}
    </Page>
  );
}
