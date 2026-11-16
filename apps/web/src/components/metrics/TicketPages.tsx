'use client';

/**
 * Metrics > Tickets and Finance (the Rewst metric dashboards, rebuilt): Ticket Resolution, Ticket Volume Analysis, Ticket Summary's open-ticket breakdown and Monthly Invoicing. A.C.O.R.N works each out from the
 * weekly and monthly facts CORE sends about once a day (HaloPSA tickets and invoices), never read live.
 */
import { useState } from 'react';

import { BarList, Cards, Columns, LONG_PERIODS, NothingYet, Page, Panel, Periods, Table, monthShort, moneyText, num, selectClass, useMetric } from './kit';

interface ResolutionData {
  received_at: string | null;
  months: string[];
  members: { engineer: string; total: number; by_month: Record<string, number> }[];
  resolution_by_client: { client: string; hours: number; tickets: number }[];
}

export function TicketResolutionView() {
  const [months, setMonths] = useState(12);
  const { data, denied, problem } = useMetric<ResolutionData>(`/api/v1/reports/metrics/ticket-resolution?months=${months}`);
  return (
    <Page title="Ticket resolution time" subtitle="Tickets resolved by each team member each month, and how long tickets take to resolve for each client." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the ticket facts" />}>
      <Periods value={months} onChange={setMonths} options={LONG_PERIODS} />
      {data?.received_at && (
        <>
          <Panel title="# of resolved tickets by team member" testId="resolved-by-member">
            <Table head={['User', 'Total', ...data.months.map(monthShort)]} rows={data.members.map((m) => [m.engineer, num(m.total), ...data.months.map((mo) => num(m.by_month[mo] ?? 0))])} />
          </Panel>
          <Panel title="Resolution time by client (in hours)" testId="resolution-by-client">
            <BarList rows={data.resolution_by_client.map((c) => ({ label: c.client, value: c.hours, text: `${num(c.hours, 1)} h (${c.tickets} tickets)` }))} limit={25} />
          </Panel>
        </>
      )}
    </Page>
  );
}

interface VolumeData {
  received_at: string | null;
  months: string[];
  total_created: number;
  by_type: { name: string; total: number; by_month: Record<string, number> }[];
  by_category: { name: string; total: number; by_month: Record<string, number> }[];
  per_month: { month: string; created: number }[];
  by_client: { client: string; created: number }[];
  priority_last_60_days: { priority: string; created: number }[];
  stale_by_tech: { tech: string; tickets: number }[];
  stale: { ticket_id: string; client: string; agent: string; title: string; priority: string; status: string; age_days: number }[];
  techs: string[];
}

export function TicketVolumeView() {
  const [months, setMonths] = useState(6);
  const [tech, setTech] = useState('');
  const { data, denied, problem } = useMetric<VolumeData>(`/api/v1/reports/metrics/ticket-volume?months=${months}${tech ? `&tech=${encodeURIComponent(tech)}` : ''}`);
  const matrix = (rows: VolumeData['by_type'], label: string, testId: string) => (
    <Panel title={label} testId={testId}>
      <Table head={['Name', 'Total', ...(data?.months ?? []).map(monthShort)]} rows={rows.map((r) => [r.name, num(r.total), ...(data?.months ?? []).map((m) => num(r.by_month[m] ?? 0))])} />
    </Panel>
  );
  return (
    <Page title="Ticket volume analysis" subtitle="Where tickets come from: by type, category, month and client, the priority mix, and tickets that have been open too long." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the ticket facts" />}>
      <Periods value={months} onChange={setMonths} options={LONG_PERIODS} />
      {data?.received_at && (
        <>
          <Cards items={[['Tickets created', num(data.total_created)], ['Stale tickets (over 30 days)', num(data.stale_by_tech.reduce((a, b) => a + b.tickets, 0))]]} />
          {matrix(data.by_type, 'Tickets created by ticket type', 'volume-by-type')}
          {matrix(data.by_category, 'Tickets created by category', 'volume-by-category')}
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Tickets created per month" testId="volume-per-month">
              <Columns points={data.per_month.map((m) => ({ label: monthShort(m.month), value: m.created }))} />
            </Panel>
            <Panel title="Ticket priority distribution (last 60 days)" testId="volume-priority">
              <BarList rows={data.priority_last_60_days.map((p) => ({ label: p.priority, value: p.created, text: num(p.created) }))} />
            </Panel>
            <Panel title="Tickets created by client" testId="volume-by-client">
              <BarList rows={data.by_client.map((c) => ({ label: c.client, value: c.created, text: num(c.created) }))} limit={25} />
            </Panel>
            <Panel title="Stale tickets by tech (open more than 30 days)" testId="stale-by-tech">
              <BarList rows={data.stale_by_tech.map((t) => ({ label: t.tech, value: t.tickets, text: num(t.tickets) }))} />
            </Panel>
          </div>
          <Panel title="Stale ticket detail" testId="stale-detail">
            <label className="mb-2 flex items-center gap-2 text-sm text-gray-300">
              Tech
              <select aria-label="Tech" className={selectClass} value={tech} onChange={(e) => setTech(e.target.value)}>
                <option value="">All techs</option>
                {data.techs.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <Table head={['Ticket', 'Client', 'Tech', 'Title', 'Priority', 'Status', 'Days open']} rows={data.stale.map((s) => [s.ticket_id, s.client, s.agent, s.title, s.priority, s.status, num(s.age_days)])} />
          </Panel>
        </>
      )}
    </Page>
  );
}

interface InvoicingData {
  received_at: string | null;
  months: string[];
  total: number;
  trend: { month: string; amount: number }[];
  by_category: { category: string; amount: number }[];
  clients: { client: string; total: number; items: { item: string; category: string; quantity: number; amount: number }[] }[];
}

export function MonthlyInvoicingView() {
  const [months, setMonths] = useState(12);
  const { data, denied, problem } = useMetric<InvoicingData>(`/api/v1/reports/metrics/monthly-invoicing?months=${months}`);
  return (
    <Page title="Monthly invoicing analysis" subtitle="What was billed, by month, by billing category and by client and invoice line. Amounts before tax." denied={denied} problem={problem} empty={<NothingYet show={data?.received_at === null} what="the invoiced lines" />}>
      <Periods value={months} onChange={setMonths} options={[1, 3, 6, 12]} />
      {data?.received_at && (
        <>
          <Cards items={[['Billed', moneyText(data.total)], ['Clients', String(data.clients.length)]]} />
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Monthly revenue trend" testId="invoicing-trend">
              <Columns points={data.trend.map((t) => ({ label: monthShort(t.month), value: Math.round(t.amount) }))} />
            </Panel>
            <Panel title="Total billed by billing category" testId="invoicing-category">
              <BarList rows={data.by_category.map((c) => ({ label: c.category, value: c.amount, text: moneyText(c.amount) }))} />
            </Panel>
          </div>
          <Panel title="Client revenue by line item" testId="invoicing-clients">
            <div className="space-y-2">
              {data.clients.map((c) => (
                <details key={c.client} className="rounded border border-gray-700 p-2">
                  <summary className="flex cursor-pointer justify-between gap-3 text-sm text-gray-200">
                    <span>{c.client}</span>
                    <span className="tabular-nums">{moneyText(c.total)}</span>
                  </summary>
                  <div className="mt-2">
                    <Table head={['Line item', 'Category', 'Quantity', 'Amount']} rows={c.items.map((i) => [i.item, i.category, num(i.quantity, 1), moneyText(i.amount)])} />
                  </div>
                </details>
              ))}
            </div>
          </Panel>
        </>
      )}
    </Page>
  );
}

interface OpenData {
  received_at: string | null;
  total: number;
  by_status: { status: string; tickets: number }[];
  by_priority: { priority: string; tickets: number }[];
}

/** What is open now by status and priority (not date filtered): the part of Ticket Summary the tickets page does not hold. */
export function OpenTicketsPanel({ clientId }: { clientId: string }) {
  const { data } = useMetric<OpenData>(`/api/v1/reports/metrics/open-tickets${clientId ? `?client_id=${encodeURIComponent(clientId)}` : ''}`);
  if (!data?.received_at || !Array.isArray(data.by_status) || !Array.isArray(data.by_priority)) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="open-breakdown">
      <Panel title="Open tickets by status (current)">
        <BarList rows={data.by_status.map((s) => ({ label: s.status, value: s.tickets, text: num(s.tickets) }))} />
      </Panel>
      <Panel title="Open tickets by priority (current)">
        <BarList rows={data.by_priority.map((s) => ({ label: s.priority, value: s.tickets, text: num(s.tickets) }))} />
      </Panel>
    </div>
  );
}
