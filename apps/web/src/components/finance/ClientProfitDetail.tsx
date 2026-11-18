'use client';

/**
 * Under the Profitability table: what one client's row is made of for the month. The invoice lines (billed, or free when the line cost the client nothing), the lines of the recurring invoice with their
 * unit cost, and the hours by agent with the hourly cost used and where it came from. Nothing here is a new number; each part adds up to a figure on the row. Reads
 * GET /api/v1/finance/profitability/client.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';

export interface ClientDetail {
  client_id: string;
  client_name: string;
  month: string;
  revenue: number;
  invoices: number;
  invoice_lines: { item: string; category: string; quantity: number; amount: number; free: boolean }[];
  invoice_lines_total: number;
  free_lines: number;
  hours: number;
  labor: number;
  after_labor: number;
  by_agent: { agent_id: string; name: string; hours: number; rate: number; rate_source: string; cost: number }[];
  by_charge_type: { charge_type: string; hours: number }[];
  recurring: { item: string; quantity: number; unit_price: number; unit_cost: number; free: boolean; cost_per_run: number }[];
  /** The tickets the month's hours went on; null when CORE has not sent ticket-level time. */
  tickets: { rows: { ticket_id: string; summary: string; hours: number; entries: number; agents: string[] }[]; other_hours: number } | null;
  invoice_lines_received_at: string | null;
}

const usd = (n: number): string => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
const qty = (n: number): string => n.toLocaleString('en-US', { maximumFractionDigits: 2 });
const SOURCE: Record<string, string> = { agent: "this agent's own rate", team: "the team's rate", default: 'the default rate (no rate set for this agent or team)' };

/** One sentence when the invoice lines do not add up to the revenue of the row, saying why that can be; empty when they match to the dollar or there are no lines (pure). */
export function linesNote(d: Pick<ClientDetail, 'revenue' | 'invoice_lines' | 'invoice_lines_total'>): string {
  if (d.invoice_lines.length === 0) return 'The invoice lines for this month have not arrived from CORE yet, or this client had none.';
  const gap = Math.round((d.revenue - d.invoice_lines_total) * 100) / 100;
  if (Math.abs(gap) < 1) return '';
  return `The lines add up to ${usd(d.invoice_lines_total)} and the row's revenue is ${usd(d.revenue)}: ${usd(Math.abs(gap))} ${gap > 0 ? 'more' : 'less'} than the lines. Invoice-level charges, a credit note or a line CORE does not read can cause that.`;
}

/** One sentence about the ticket list: how many are shown and the hours on tickets that are not (pure). */
export function ticketsNote(t: NonNullable<ClientDetail['tickets']>): string {
  if (t.rows.length === 0 && t.other_hours <= 0) return 'No hours were worked on tickets this month.';
  const shown = `${t.rows.length} ticket${t.rows.length === 1 ? ' has' : 's have'} time logged on ${t.rows.length === 1 ? 'it' : 'them'} this month; press a heading to sort.`;
  return t.other_hours > 0 ? `${shown} ${qty(t.other_hours)} more hours are not on a ticket listed here.` : shown;
}

export function ClientProfitDetail({ clientId, month, onClose, focus }: { clientId: string; month: string; onClose: () => void; focus?: 'tickets' }) {
  const [d, setD] = useState<ClientDetail | null>(null);
  const [ticketSort, setTicketSort] = useState<SortState | null>({ key: 'hours', desc: true });
  const ticketsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Opened by pressing the hours: take the person to the tickets those hours went on.
    if (focus === 'tickets' && d) ticketsRef.current?.scrollIntoView?.({ block: 'start' });
  }, [focus, d]);
  const ticketRows = useMemo(
    () => (d?.tickets ? sortedBy(d.tickets.rows, (t) => (ticketSort ? ((t as unknown as Record<string, unknown>)[ticketSort.key] as SortValue) : t.hours), ticketSort?.desc ?? true) : []),
    [d, ticketSort],
  );
  const [problem, setProblem] = useState('');
  useEffect(() => {
    let live = true;
    setD(null);
    setProblem('');
    authFetch(`/api/v1/finance/profitability/client?client_id=${encodeURIComponent(clientId)}&month=${encodeURIComponent(month)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? 'That client was not invoiced in this month.' : `The API answered ${res.status}`);
        return (await res.json()) as ClientDetail;
      })
      .then((x) => live && setD(x))
      .catch((e) => live && setProblem(e instanceof Error ? e.message : 'Could not load'));
    return () => {
      live = false;
    };
  }, [clientId, month]);
  const cell = 'px-3 py-1.5';
  return (
    <section aria-label="Where this client's numbers come from" className="space-y-4 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="client-profit-detail">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold text-gray-100">{d ? `${d.client_name}: where the numbers come from` : 'Loading…'}</h2>
        <button type="button" onClick={onClose} className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-800">
          Close
        </button>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-amber-300">
          {problem}
        </p>
      )}
      {d && (
        <>
          <p className="text-sm text-gray-300">
            Revenue <span className="text-gray-100">{usd(d.revenue)}</span> from {d.invoices} invoice{d.invoices === 1 ? '' : 's'}, less labor <span className="text-gray-100">{usd(d.labor)}</span> ({qty(d.hours)} hours) leaves{' '}
            <span className="text-gray-100">{usd(d.after_labor)}</span>.
          </p>

          <div>
            <h3 className="text-sm font-medium text-gray-200">
              Invoice lines <span className="text-xs text-gray-500">({d.invoice_lines.length} lines, {d.free_lines} free)</span>
            </h3>
            {d.invoice_lines.length > 0 && (
              <div className="mt-1 overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="detail-invoice-lines">
                  <thead className="text-xs uppercase text-gray-500">
                    <tr>
                      <th className={cell}>Item</th>
                      <th className={cell}>Category</th>
                      <th className={`${cell} text-right`}>Quantity</th>
                      <th className={`${cell} text-right`}>Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800 text-gray-200">
                    {d.invoice_lines.map((l, i) => (
                      <tr key={`${l.item}-${i}`}>
                        <td className={cell}>
                          {l.item} {l.free && <span className="ml-1 rounded-full border border-emerald-500/40 px-1.5 text-[10px] uppercase text-emerald-300">free</span>}
                        </td>
                        <td className={`${cell} text-gray-400`}>{l.category}</td>
                        <td className={`${cell} text-right tabular-nums`}>{qty(l.quantity)}</td>
                        <td className={`${cell} text-right tabular-nums`}>{usd(l.amount)}</td>
                      </tr>
                    ))}
                    <tr className="font-medium">
                      <td className={cell} colSpan={3}>
                        Lines total
                      </td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(d.invoice_lines_total)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
            {linesNote(d) && (
              <p className="mt-1 text-xs text-gray-400" data-testid="detail-lines-note">
                {linesNote(d)}
              </p>
            )}
          </div>

          <div>
            <h3 className="text-sm font-medium text-gray-200">Recurring invoice, each run</h3>
            {d.recurring.length === 0 ? (
              <p className="text-xs text-gray-500">No recurring invoice lines are held for this client.</p>
            ) : (
              <table className="mt-1 w-full text-left text-sm" data-testid="detail-recurring">
                <thead className="text-xs uppercase text-gray-500">
                  <tr>
                    <th className={cell}>Item</th>
                    <th className={`${cell} text-right`}>Quantity</th>
                    <th className={`${cell} text-right`}>Price each</th>
                    <th className={`${cell} text-right`}>Cost each</th>
                    <th className={`${cell} text-right`}>Cost per run</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 text-gray-200">
                  {d.recurring.map((r, i) => (
                    <tr key={`${r.item}-${i}`}>
                      <td className={cell}>
                        {r.item} {r.free && <span className="ml-1 rounded-full border border-emerald-500/40 px-1.5 text-[10px] uppercase text-emerald-300">free</span>}
                      </td>
                      <td className={`${cell} text-right tabular-nums`}>{qty(r.quantity)}</td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(r.unit_price)}</td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(r.unit_cost)}</td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(r.cost_per_run)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <h3 className="text-sm font-medium text-gray-200">Hours and labor cost</h3>
            {d.by_agent.length === 0 ? (
              <p className="text-xs text-gray-500">No time was logged for this client in this month.</p>
            ) : (
              <table className="mt-1 w-full text-left text-sm" data-testid="detail-agents">
                <thead className="text-xs uppercase text-gray-500">
                  <tr>
                    <th className={cell}>Team member</th>
                    <th className={`${cell} text-right`}>Hours</th>
                    <th className={`${cell} text-right`}>Hourly cost</th>
                    <th className={cell}>Rate from</th>
                    <th className={`${cell} text-right`}>Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 text-gray-200">
                  {d.by_agent.map((a) => (
                    <tr key={a.agent_id}>
                      <td className={cell}>{a.name}</td>
                      <td className={`${cell} text-right tabular-nums`}>{qty(a.hours)}</td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(a.rate)}</td>
                      <td className={`${cell} text-xs text-gray-400`}>{SOURCE[a.rate_source] ?? a.rate_source}</td>
                      <td className={`${cell} text-right tabular-nums`}>{usd(a.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {d.by_charge_type.length > 0 && (
              <p className="mt-1 text-xs text-gray-400" data-testid="detail-charge-types">
                By charge type: {d.by_charge_type.map((c) => `${c.charge_type} ${qty(c.hours)} h`).join(', ')}.
              </p>
            )}
          </div>

          <div ref={ticketsRef}>
            <h3 className="text-sm font-medium text-gray-200">Tickets</h3>
            <p className="text-xs text-gray-500" data-testid="detail-tickets">
              {d.tickets === null ? 'The tickets behind these hours are not sent by CORE yet, so only the people and charge types are shown.' : ticketsNote(d.tickets)}
            </p>
            {d.tickets !== null && d.tickets.rows.length > 0 && (
              <table className="mt-2 w-full text-left text-sm" aria-label="Tickets behind the hours" data-testid="detail-ticket-rows">
                <thead className="text-xs uppercase text-gray-500">
                  <tr>
                    <SortHeader label="Ticket" field="ticket_id" sort={ticketSort} onSort={setTicketSort} className={cell} />
                    <SortHeader label="Subject" field="summary" sort={ticketSort} onSort={setTicketSort} text className={cell} />
                    <SortHeader label="Hours" field="hours" sort={ticketSort} onSort={setTicketSort} className={`${cell} text-right`} />
                    <SortHeader label="Entries" field="entries" sort={ticketSort} onSort={setTicketSort} className={`${cell} text-right`} />
                    <th className={cell}>Worked by</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 text-gray-200">
                  {ticketRows.map((t) => (
                    <tr key={t.ticket_id}>
                      <td className={`${cell} tabular-nums`}>#{t.ticket_id}</td>
                      <td className={cell}>{t.summary || '(no subject)'}</td>
                      <td className={`${cell} text-right tabular-nums`}>{qty(t.hours)}</td>
                      <td className={`${cell} text-right tabular-nums`}>{t.entries}</td>
                      <td className={`${cell} text-xs text-gray-400`}>{t.agents.join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </section>
  );
}
