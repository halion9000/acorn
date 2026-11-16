'use client';

/**
 * Metrics > Customer Insights (the Rewst metric dashboards, rebuilt): Customer Experience, Monthly Licensing and User Roles. Satisfaction comes from SimpleSat, license counts from the tools, and Microsoft 365
 * roles from CIPP: CORE sends them about once a day and A.C.O.R.N reads its own copy.
 */
import { useState } from 'react';

import { Cards, NothingYet, Page, Panel, Periods, Table, monthShort, num, pctText, selectClass, useMetric } from './kit';

interface Bucket {
  responses: number;
  positive: number;
  neutral: number;
  negative: number;
  csat: number | null;
  neutral_percent: number | null;
  negative_percent: number | null;
}
interface ExperienceData {
  received_at: string | null;
  months: string[];
  overall: (Bucket & { name: string }) | null;
  by_company: (Bucket & { company: string })[];
  by_member: (Bucket & { member: string })[];
  by_month: (Bucket & { month: string })[];
  recent: { company: string; date: string; contact: string; sentiment: string | null; rating: string; comment: string; ticket_id: string }[];
}

const SENTIMENTS: [string, string][] = [
  ['all', 'All responses'],
  ['positive', 'Positive only'],
  ['neutral', 'Neutral only'],
  ['negative', 'Negative only'],
];

export function CustomerExperienceView() {
  const [months, setMonths] = useState(12);
  const [sentiment, setSentiment] = useState('all');
  const { data, denied, problem } = useMetric<ExperienceData>(`/api/v1/reports/metrics/customer-experience?months=${months}&sentiment=${sentiment}`);
  const cells = (b: Bucket): string[] => [num(b.responses), pctText(b.csat), String(b.positive), String(b.neutral), String(b.negative), pctText(b.neutral_percent), pctText(b.negative_percent)];
  const head = ['Responses', 'CSAT', 'Positive', 'Neutral', 'Negative', 'Neutral %', 'Negative %'];
  return (
    <Page title="Customer experience" subtitle="How customers rate the help they got, from SimpleSat surveys." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the SimpleSat summary" />}>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Filter by
          <select aria-label="Filter by" className={selectClass} value={sentiment} onChange={(e) => setSentiment(e.target.value)}>
            {SENTIMENTS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <Periods value={months} onChange={setMonths} options={[1, 3, 6, 12]} />
      </div>
      {data?.received_at && (
        <>
          {data.overall && <Cards items={[['Responses', num(data.overall.responses)], ['CSAT', pctText(data.overall.csat)], ['Positive', String(data.overall.positive)], ['Negative', String(data.overall.negative)]]} />}
          <Panel title="Breakdown by company" testId="exp-company">
            <Table head={['Company', ...head]} rows={data.by_company.map((c) => [c.company, ...cells(c)])} />
          </Panel>
          <Panel title="Team members breakdown" testId="exp-member">
            <Table head={['Team member', ...head]} rows={data.by_member.map((c) => [c.member, ...cells(c)])} />
          </Panel>
          <Panel title="Monthly breakdown" testId="exp-month">
            <Table head={['Period', ...head]} rows={data.by_month.map((c) => [monthShort(c.month), ...cells(c)])} />
          </Panel>
          <Panel title="Recent responses" testId="exp-recent">
            <ul className="space-y-1">
              {data.recent.slice(0, 20).map((r, i) => (
                <li key={`${r.date}-${i}`} className="text-sm text-gray-200">
                  <span className={r.sentiment === 'negative' ? 'text-red-300' : r.sentiment === 'positive' ? 'text-emerald-300' : 'text-gray-300'}>{r.rating || r.sentiment || 'No rating'}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {r.company}, {r.date.slice(0, 10)}
                    {r.contact ? `, ${r.contact}` : ''}
                  </span>
                  {r.comment && <span className="block text-xs text-gray-300">{r.comment}</span>}
                </li>
              ))}
              {data.recent.length === 0 && <li className="text-sm text-gray-500">No responses of that kind.</li>}
            </ul>
          </Panel>
        </>
      )}
    </Page>
  );
}

interface LicensingData {
  received_at: string | null;
  month: string;
  as_of: string;
  items: { key: string; source: string; item: string; unit: string; total: number }[];
  clients: { client_id: string; client: string; counts: Record<string, number> }[];
}

/** The last twelve months, newest first, as YYYY-MM (pure). */
export function recentMonths(now: Date = new Date(), count = 12): string[] {
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
  });
}

export function MonthlyLicensingView() {
  const [month, setMonth] = useState(() => recentMonths()[0]!);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const { data, denied, problem } = useMetric<LicensingData>(`/api/v1/reports/metrics/monthly-licensing?month=${month}`);
  const shown = (data?.items ?? []).filter((i) => !hidden.has(i.key));
  const toggle = (k: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  return (
    <Page title="Monthly licensing" subtitle="What each client had of each license and counted item, as of the end of the month chosen (this month is what is counted now)." denied={denied} problem={problem} empty={null}>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Month
          <select aria-label="Month" className={selectClass} value={month} onChange={(e) => setMonth(e.target.value)}>
            {recentMonths().map((m) => (
              <option key={m} value={m}>
                {monthShort(m)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800" onClick={() => setHidden(new Set())}>
          Select all
        </button>
      </div>
      {data && (
        <>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-300" aria-label="Items">
            {data.items.map((i) => (
              <label key={i.key} className="flex items-center gap-1">
                <input type="checkbox" checked={!hidden.has(i.key)} onChange={() => toggle(i.key)} /> {i.item} ({i.source})
              </label>
            ))}
          </fieldset>
          {data.clients.length === 0 ? (
            <p className="text-sm text-gray-400" data-testid="licensing-empty">
              Nothing was counted for any client {data.as_of === 'now' ? 'yet' : `by the end of ${monthShort(month)}`}.
            </p>
          ) : (
            <Table
              testId="licensing-table"
              head={['Client name', ...shown.map((i) => i.item)]}
              rows={[...data.clients.map((c) => [c.client, ...shown.map((i) => (c.counts[i.key] === undefined ? '' : num(c.counts[i.key])))]), ['Total', ...shown.map((i) => num(i.total))]]}
            />
          )}
        </>
      )}
    </Page>
  );
}

interface RolesData {
  received_at: string | null;
  roles: { role: string; total: number }[];
  clients: { client_id: string; client: string; counts: Record<string, number>; members: Record<string, { name: string; upn: string; enabled: boolean }[]> }[];
}

export function UserRolesView() {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const { data, denied, problem } = useMetric<RolesData>('/api/v1/reports/metrics/user-roles');
  const shown = (data?.roles ?? []).filter((r) => !hidden.has(r.role));
  const toggle = (k: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  return (
    <Page title="User roles" subtitle="How many people hold each Microsoft 365 administrator role at each client, and who." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the Microsoft 365 roles" />}>
      {data?.received_at && (
        <>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-300" aria-label="Roles">
            <button type="button" className="text-blue-300 hover:underline" onClick={() => setHidden(new Set())}>
              Select all
            </button>
            {data.roles.map((r) => (
              <label key={r.role} className="flex items-center gap-1">
                <input type="checkbox" checked={!hidden.has(r.role)} onChange={() => toggle(r.role)} /> {r.role} ({r.total})
              </label>
            ))}
          </fieldset>
          <Table testId="roles-table" head={['Client name', ...shown.map((r) => r.role)]} rows={data.clients.map((c) => [c.client, ...shown.map((r) => (c.counts[r.role] === undefined ? '' : num(c.counts[r.role])))])} />
          <div className="space-y-2">
            {data.clients.map((c) => (
              <details key={c.client_id || c.client} className="rounded border border-gray-700 p-2">
                <summary className="cursor-pointer text-sm text-gray-200">{c.client}: who</summary>
                <ul className="mt-2 space-y-1 text-xs text-gray-300">
                  {Object.entries(c.members).map(([role, people]) => (
                    <li key={role}>
                      <span className="text-gray-400">{role}:</span> {people.map((p) => `${p.name || p.upn}${p.enabled ? '' : ' (disabled)'}`).join(', ')}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </>
      )}
    </Page>
  );
}
