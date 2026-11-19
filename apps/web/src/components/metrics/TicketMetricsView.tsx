'use client';

/**
 * Metrics > Tickets and satisfaction (the Rewst metric dashboards, rebuilt): tickets created and resolved, first response, tickets by type and by who resolved them, what is open, and customer satisfaction from
 * SimpleSat, for all clients or one, over the last 1, 3, 6 or 12 months. HaloPSA's numbers reach A.C.O.R.N once a day; satisfaction comes from SimpleSat through CORE.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { PageHeader } from '@/components/ui/kit';
import { MetricStat, PairedColumns, showingText } from './kit';
import { OpenTicketsPanel } from './TicketPages';

interface Summary {
  months: string[];
  series: { month: string; created: number; resolved: number }[];
  created: number;
  resolved: number;
  created_per_month: number | null;
  resolved_per_month: number | null;
  first_response_minutes: number | null;
  by_type: { type: string; tickets: number }[];
  resolved_by_agent: { agent_id: string; name: string; tickets: number }[];
  open_now: { total: number; critical: number; high: number };
}
interface TicketData {
  received_at: string | null;
  clients: { client_id: string; client_name: string }[];
  summary: Summary | null;
  available_months?: number;
}
interface CsatSummary {
  months: string[];
  responses: number;
  positive: number;
  neutral: number;
  negative: number;
  satisfied_percent: number | null;
  trend: { month: string; positive: number; neutral: number; negative: number; total: number; satisfied_percent: number | null }[];
  recent: { company: string; date: string; contact: string; sentiment: string | null; rating: string; comment: string; ticket_id: string }[];
}
interface CsatData {
  received_at: string | null;
  companies: string[];
  summary: CsatSummary | null;
}

export const PERIODS = [1, 3, 6, 12, 24, 36] as const;
export const num = (n: number | null | undefined, unit = ''): string => (n === null || n === undefined ? '—' : `${n.toLocaleString('en-US')}${unit}`);
/** A wait in minutes as people say it: "18 min", "2 h 5 min", "1 d 3 h". */
export function waitText(minutes: number | null): string {
  if (minutes === null) return '—';
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  if (h < 24) return `${h} h ${Math.round(minutes - h * 60)} min`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}
export const monthName = (m: string): string => {
  const [y, mo] = m.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' });
};
const key = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
/** The SimpleSat company whose name matches the client chosen (ignoring case and punctuation), or '' (pure). */
export function companyFor(clientName: string, companies: string[]): string {
  return companies.find((c) => key(c) === key(clientName)) ?? '';
}

const card = 'rounded-lg border border-gray-700 bg-gray-800 p-3';
const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;

export function TicketMetricsView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [months, setMonths] = useState<number>(3);
  const [clientId, setClientId] = useState('');
  const [tickets, setTickets] = useState<TicketData | null>(null);
  const [csat, setCsat] = useState<CsatData | null>(null);

  const load = useCallback(async (m: number, client: string, companyName: string | null) => {
    try {
      const t = await authFetch(`/api/v1/reports/ticket-metrics?months=${m}${client ? `&client_id=${encodeURIComponent(client)}` : ''}`);
      if (t.status === 403) {
        setDenied(true);
        return;
      }
      if (!t.ok) throw new Error(`The API answered ${t.status}`);
      const body = (await t.json()) as TicketData;
      setTickets(body);
      const chosenName = client ? (body.clients.find((c) => c.client_id === client)?.client_name ?? '') : '';
      const sat = await authFetch(`/api/v1/reports/ticket-metrics/csat?months=${Math.min(m, 12)}${client && (companyName ?? chosenName) ? `&company=${encodeURIComponent(companyName ?? chosenName)}` : ''}`);
      if (sat.ok) setCsat((await sat.json()) as CsatData);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load(months, clientId, null);
  }, [load, months, clientId]);

  if (denied) return <p className="p-6 text-sm text-amber-300">Ticket metrics need the report permission. Ask the owner to add it to your role.</p>;
  const s = tickets?.summary;
  const sat = csat?.summary;
  const max = Math.max(1, ...(s?.series ?? []).flatMap((r) => [r.created, r.resolved]));
  return (
    <div className="p-6">
    <div className="metrics-shell space-y-4">
      <PageHeader title="Tickets and satisfaction" subtitle="Tickets created and resolved, how fast we first answer, what is open and how clients rate us. Updated about once a day." />
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Client
          <select aria-label="Client" className="rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">All clients</option>
            {(tickets?.clients ?? []).map((c) => (
              <option key={c.client_id} value={c.client_id}>
                {c.client_name}
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Period" className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={months === p} className={pill(months === p)} onClick={() => setMonths(p)}>
              {p === 1 ? 'Last month' : `Last ${p} months`}
            </button>
          ))}
        </div>
      </div>
      {s && tickets?.received_at ? (
        <p className="text-xs" style={{ color: 'var(--metrics-soft)' }} data-testid="ticket-showing">
          {showingText(s.months, tickets.available_months ?? s.months.length)}
        </p>
      ) : null}
      {tickets && tickets.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="tickets-empty">
          Nothing has arrived from HaloPSA yet. CORE sends the ticket summary about once a day once HaloPSA is connected in CORE.
        </p>
      )}
      {s && tickets?.received_at && (
        <>
          <section className="metrics-card" aria-label="Ticket volume">
            <h2 className="text-base">Ticket volume</h2>
            <div className="mb-4">
              <PairedColumns points={s.series.map((r) => ({ label: monthName(r.month), a: r.created, b: r.resolved }))} aLabel="Created" bLabel="Resolved" />
              <p className="mt-2 text-[11px] text-gray-500">A ticket is counted as resolved in the month it was closed.</p>
            </div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6" data-testid="ticket-cards">
              {[
                ['Created', num(s.created), `${num(s.created_per_month)} a month`],
                ['Resolved', num(s.resolved), `${num(s.resolved_per_month)} a month`],
                ['First response', waitText(s.first_response_minutes), 'on average, from HaloPSA'],
                ['Open now', num(s.open_now.total), ''],
                ['Critical open', num(s.open_now.critical), ''],
                ['High open', num(s.open_now.high), ''],
              ].map(([label, value, note]) => (
                <MetricStat key={label} label={label} value={value} note={note || undefined} />
              ))}
            </div>
          </section>
          <OpenTicketsPanel clientId={clientId} />
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="metrics-card" aria-label="By type">
              <h2 className="text-base">Tickets by type</h2>
              <ul className="text-sm text-gray-300" data-testid="ticket-types">
                {s.by_type.slice(0, 12).map((t) => (
                  <li key={t.type} className="flex justify-between">
                    <span>{t.type}</span>
                    <span>{num(t.tickets)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="metrics-card" aria-label="By engineer">
              <h2 className="text-base">Tickets resolved by engineer</h2>
              <ul className="text-sm text-gray-300" data-testid="ticket-agents">
                {s.resolved_by_agent.slice(0, 12).map((a) => (
                  <li key={a.agent_id} className="flex justify-between">
                    <span>{a.name}</span>
                    <span>{num(a.tickets)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
      {csat && csat.received_at === null && <p className="text-sm text-gray-400" data-testid="csat-empty">Customer satisfaction appears once SimpleSat is connected in CORE.</p>}
      {sat && csat?.received_at && (
        <section className="metrics-card space-y-3" aria-label="Customer satisfaction" data-testid="csat">
          <h2 className="text-base">Customer satisfaction</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              ['Satisfied', sat.satisfied_percent === null ? '—' : `${sat.satisfied_percent}%`],
              ['Responses', num(sat.responses)],
              ['Positive', num(sat.positive)],
              ['Neutral', num(sat.neutral)],
              ['Negative', num(sat.negative)],
            ].map(([label, value]) => (
              <div key={label} className={card}>
                <p className="text-xl font-semibold text-white">{value}</p>
                <p className="text-xs text-gray-400">{label}</p>
              </div>
            ))}
          </div>
          <ul className="text-xs text-gray-300" data-testid="csat-trend">
            {sat.trend.map((t) => (
              <li key={t.month}>
                {monthName(t.month)}: {t.satisfied_percent === null ? 'no ratings' : `${t.satisfied_percent}% satisfied`} ({t.total} response{t.total === 1 ? '' : 's'})
              </li>
            ))}
          </ul>
          <div>
            <h3 className="mb-1 text-xs uppercase text-gray-500">Recent responses</h3>
            <ul className="space-y-1 text-sm" data-testid="csat-recent">
              {sat.recent.slice(0, 10).map((r, i) => (
                <li key={`${r.date}-${i}`} className="rounded border border-gray-800 px-3 py-1.5">
                  <span className={r.sentiment === 'negative' ? 'text-red-300' : r.sentiment === 'positive' ? 'text-emerald-300' : 'text-gray-300'}>{r.rating || r.sentiment || 'No rating'}</span>
                  <span className="ml-2 text-gray-400">
                    {r.contact || 'Someone'} at {r.company}, {r.date.slice(0, 10)}
                    {r.ticket_id ? `, ticket ${r.ticket_id}` : ''}
                  </span>
                  {r.comment && <p className="text-xs text-gray-300">{r.comment}</p>}
                </li>
              ))}
              {sat.recent.length === 0 && <li className="text-gray-500">No responses in this period.</li>}
            </ul>
          </div>
        </section>
      )}
    </div>
    </div>
  );
}
