'use client';

/**
 * Metrics > Client summary (the Rewst End User Dashboard, rebuilt for staff): one client's tickets, labor hours and satisfaction on one printable page, for a review meeting or to send as a PDF. It reads
 * A.C.O.R.N's own database, filled by CORE once a day, never HaloPSA live. Opening it to the client's own people needs a client sign-in, which is not built: that is the owner's call.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { hoursText, monthName } from './LaborHoursView';
import { PERIODS, num, waitText } from './TicketMetricsView';

interface Tickets {
  received_at: string | null;
  clients: { client_id: string; client_name: string }[];
  summary: {
    created: number;
    resolved: number;
    created_per_month: number | null;
    resolved_per_month: number | null;
    first_response_minutes: number | null;
    by_type: { type: string; tickets: number }[];
    resolved_by_agent: { agent_id: string; name: string; tickets: number }[];
    open_now: { total: number; critical: number; high: number };
  } | null;
}
interface Labor {
  summary: { total_hours: number; hours_per_month: number | null; by_month: { month: string; hours: number }[]; by_type: { type: string; hours: number }[] } | null;
}
interface Csat {
  companies: string[];
  summary: {
    responses: number;
    positive: number;
    neutral: number;
    negative: number;
    satisfied_percent: number | null;
    recent: { date: string; contact: string; sentiment: string | null; rating: string; comment: string }[];
  } | null;
}

const key = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
/** The name SimpleSat and the hours use for the client chosen (they match on name, ignoring case and punctuation), or '' (pure). */
export function nameIn(clientName: string, names: string[]): string {
  return names.find((n) => key(n) === key(clientName)) ?? '';
}
const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;
const card = 'rounded-lg border border-gray-700 bg-gray-800 p-3';

export function ClientSummaryView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [months, setMonths] = useState<number>(3);
  const [clientId, setClientId] = useState('');
  const [tickets, setTickets] = useState<Tickets | null>(null);
  const [labor, setLabor] = useState<Labor | null>(null);
  const [csat, setCsat] = useState<Csat | null>(null);

  const load = useCallback(async (m: number, id: string, known: Tickets['clients']) => {
    try {
      const t = await authFetch(`/api/v1/reports/ticket-metrics?months=${m}${id ? `&client_id=${encodeURIComponent(id)}` : ''}`);
      if (t.status === 403) {
        setDenied(true);
        return;
      }
      if (!t.ok) throw new Error(`The API answered ${t.status}`);
      const body = (await t.json()) as Tickets;
      setTickets(body);
      const name = body.clients.concat(known).find((c) => c.client_id === id)?.client_name ?? '';
      const l = await authFetch(`/api/v1/reports/ticket-metrics/labor-hours?months=${m}${name ? `&client=${encodeURIComponent(name)}` : ''}`);
      if (l.ok) setLabor((await l.json()) as Labor);
      const s = await authFetch(`/api/v1/reports/ticket-metrics/csat?months=${m}${name ? `&company=${encodeURIComponent(name)}` : ''}`);
      if (s.ok) {
        const sb = (await s.json()) as Csat;
        const company = name ? nameIn(name, sb.companies) : '';
        if (name && !company) setCsat({ companies: sb.companies, summary: null });
        else setCsat(sb);
      }
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load(months, clientId, tickets?.clients ?? []);
    // the client list is only needed to turn the chosen id into a name, and it arrives with the first answer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, months, clientId]);

  if (denied) return <p className="p-6 text-sm text-amber-300">The client summary needs the metrics permission. Ask the owner to add it to your role.</p>;
  const t = tickets?.summary;
  const l = labor?.summary;
  const sat = csat?.summary;
  const clientName = tickets?.clients.find((c) => c.client_id === clientId)?.client_name ?? 'All clients';
  return (
    <div className="space-y-5 p-6 print:p-0" data-testid="client-summary">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Client summary: {clientName}</h1>
          <p className="mt-1 text-sm text-gray-400">The last {months === 1 ? 'month' : `${months} months`} of tickets, hours and satisfaction, from HaloPSA and SimpleSat as of the last daily read.</p>
        </div>
        <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 print:hidden" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      <div className="flex flex-wrap items-center gap-3 print:hidden">
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
      {tickets && tickets.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="summary-empty">
          Nothing has arrived from HaloPSA yet. CORE sends the summaries about once a day once HaloPSA is connected in CORE.
        </p>
      )}
      {t && (
        <section data-testid="summary-tickets">
          <h2 className="mb-2 text-sm font-semibold text-white">Tickets</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Created', num(t.created), `${num(t.created_per_month)} a month`],
              ['Resolved', num(t.resolved), `${num(t.resolved_per_month)} a month`],
              ['First response', waitText(t.first_response_minutes), 'on average'],
              ['Open now', num(t.open_now.total), `${t.open_now.critical} critical, ${t.open_now.high} high`],
            ].map(([label, value, sub]) => (
              <div key={label} className={card}>
                <p className="text-xl font-semibold text-white">{value}</p>
                <p className="text-xs text-gray-400">
                  {label}
                  {sub ? `, ${sub}` : ''}
                </p>
              </div>
            ))}
          </div>
          {t.by_type.length > 0 && (
            <p className="mt-2 text-sm text-gray-300">
              By type: {t.by_type.slice(0, 6).map((r) => `${r.type} ${r.tickets}`).join(', ')}.
            </p>
          )}
          {t.resolved_by_agent.length > 0 && (
            <p className="mt-1 text-sm text-gray-300">
              Resolved by: {t.resolved_by_agent.slice(0, 6).map((r) => `${r.name} ${r.tickets}`).join(', ')}.
            </p>
          )}
        </section>
      )}
      {l && (
        <section data-testid="summary-hours">
          <h2 className="mb-2 text-sm font-semibold text-white">Hours worked</h2>
          <p className="text-sm text-gray-300">
            {hoursText(l.total_hours)} in all, {hoursText(l.hours_per_month)} a month. {l.by_month.map((m) => `${monthName(m.month)} ${hoursText(m.hours)}`).join(', ')}.
          </p>
          {l.by_type.length > 0 && <p className="mt-1 text-sm text-gray-300">By type: {l.by_type.slice(0, 6).map((r) => `${r.type} ${hoursText(r.hours)}`).join(', ')}.</p>}
        </section>
      )}
      <section data-testid="summary-csat">
        <h2 className="mb-2 text-sm font-semibold text-white">Customer satisfaction</h2>
        {!sat || sat.responses === 0 ? (
          <p className="text-sm text-gray-500">No survey responses in this period.</p>
        ) : (
          <>
            <p className="text-sm text-gray-300">
              {sat.responses} responses: {sat.positive} positive, {sat.neutral} neutral, {sat.negative} negative
              {sat.satisfied_percent !== null ? `, ${sat.satisfied_percent}% satisfied` : ''}.
            </p>
            <ul className="mt-2 space-y-1">
              {sat.recent.slice(0, 5).map((r, i) => (
                <li key={`${r.date}-${i}`} className="text-sm text-gray-200">
                  <span className={r.sentiment === 'negative' ? 'text-red-300' : r.sentiment === 'positive' ? 'text-emerald-300' : 'text-gray-300'}>{r.rating || r.sentiment || 'No rating'}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {r.date.slice(0, 10)}
                    {r.contact ? `, ${r.contact}` : ''}
                  </span>
                  {r.comment && <span className="block text-xs text-gray-300">{r.comment}</span>}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
