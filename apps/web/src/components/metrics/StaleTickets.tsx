'use client';

import { useMemo, useState } from 'react';

export interface StaleTicket {
  ticket_id: string;
  client: string;
  agent: string;
  title: string;
  priority: string;
  status: string;
  age_days: number;
  type?: string;
  opened?: string;
  last_activity?: string;
  idle_days?: number | null;
}

export type AgeBand = 'any' | '30-60' | '61-120' | '121+';

/** The age band a ticket falls in: 30-60 days, 61-120 days or 121 and over. */
export function ageBand(days: number): Exclude<AgeBand, 'any'> {
  return days > 120 ? '121+' : days > 60 ? '61-120' : '30-60';
}

export interface TechGroup {
  tech: string;
  tickets: StaleTicket[];
  bands: Record<Exclude<AgeBand, 'any'>, number>;
}

/** The tickets that pass the age band and the search words, grouped by tech, the tech with most tickets first (pure). */
export function groupByTech(tickets: StaleTicket[], band: AgeBand, search: string, tech: string): TechGroup[] {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  const groups = new Map<string, TechGroup>();
  for (const t of tickets) {
    const name = t.agent || 'Unassigned';
    if (tech && name !== tech) continue;
    if (band !== 'any' && ageBand(t.age_days) !== band) continue;
    const hay = `${t.ticket_id} ${t.client} ${t.title} ${t.type ?? ''} ${t.status}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) continue;
    const g = groups.get(name) ?? { tech: name, tickets: [], bands: { '30-60': 0, '61-120': 0, '121+': 0 } };
    g.tickets.push(t);
    g.bands[ageBand(t.age_days)] += 1;
    groups.set(name, g);
  }
  return [...groups.values()].sort((a, b) => b.tickets.length - a.tickets.length || a.tech.localeCompare(b.tech));
}

const FIELD = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const BTN = 'rounded-md border border-gray-700 px-2 py-1 text-xs text-gray-200';
const BADGE: Record<string, { bg: string; fg: string }> = {
  '30-60': { bg: 'rgba(156,163,175,0.22)', fg: '#e5e7eb' },
  '61-120': { bg: 'rgba(245,158,11,0.22)', fg: '#fbbf24' },
  '121+': { bg: 'rgba(239,68,68,0.22)', fg: '#f87171' },
  total: { bg: 'rgba(56,189,248,0.22)', fg: '#7dd3fc' },
};

function Badge({ kind, children }: { kind: keyof typeof BADGE; children: React.ReactNode }) {
  return (
    <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: BADGE[kind]!.bg, color: BADGE[kind]!.fg }}>
      {children}
    </span>
  );
}

const HEAD = ['Ticket', 'Days Old', 'Client', 'Type', 'Summary', 'Status', 'Opened', 'Last Activity', 'Days Idle'];

export function StaleDetail({ tickets }: { tickets: StaleTicket[] }) {
  const [tech, setTech] = useState('');
  const [band, setBand] = useState<AgeBand>('any');
  const [search, setSearch] = useState('');
  // Which groups the person opened or closed; before any choice the first group is open.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const techs = useMemo(() => [...new Set(tickets.map((t) => t.agent || 'Unassigned'))].sort((a, b) => a.localeCompare(b)), [tickets]);
  const groups = useMemo(() => groupByTech(tickets, band, search, tech), [tickets, band, search, tech]);
  const isOpen = (g: TechGroup, i: number): boolean => open[g.tech] ?? i === 0;
  const setAll = (value: boolean) => setOpen(Object.fromEntries(groups.map((g) => [g.tech, value])));
  const reset = () => {
    setTech('');
    setBand('any');
    setSearch('');
    setOpen({});
  };
  return (
    <div data-testid="stale-detail-groups">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs uppercase tracking-wide text-gray-400">
        Tech
        <select aria-label="Tech" className={FIELD} value={tech} onChange={(e) => setTech(e.target.value)}>
          <option value="">{`All techs (${techs.length})`}</option>
          {techs.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        Age
        <select aria-label="Age" className={FIELD} value={band} onChange={(e) => setBand(e.target.value as AgeBand)}>
          <option value="any">Any age</option>
          <option value="30-60">30-60 days</option>
          <option value="61-120">61-120 days</option>
          <option value="121+">121+ days</option>
        </select>
        <input aria-label="Search" className={`${FIELD} min-w-[12rem] flex-1`} placeholder="Search ticket #, client, summary..." value={search} onChange={(e) => setSearch(e.target.value)} />
        <button type="button" className={BTN} onClick={() => setAll(true)}>
          Expand all
        </button>
        <button type="button" className={BTN} onClick={() => setAll(false)}>
          Collapse all
        </button>
        <button type="button" className={BTN} onClick={reset}>
          Reset
        </button>
      </div>
      {groups.length === 0 && <p className="text-sm text-gray-400">No stale tickets match.</p>}
      <div className="space-y-2">
        {groups.map((g, i) => (
          <section key={g.tech} className="rounded-lg border border-gray-800 bg-gray-900/40" aria-label={g.tech}>
            <button type="button" aria-expanded={isOpen(g, i)} onClick={() => setOpen({ ...open, [g.tech]: !isOpen(g, i) })} className="flex w-full items-center gap-3 px-3 py-2 text-left">
              <span aria-hidden className="text-xs text-gray-400">
                {isOpen(g, i) ? '▾' : '▸'}
              </span>
              <span className="flex-1 font-semibold text-gray-100">{g.tech}</span>
              {g.bands['30-60'] > 0 && <Badge kind="30-60">{g.bands['30-60']} @ 30-60</Badge>}
              {g.bands['61-120'] > 0 && <Badge kind="61-120">{g.bands['61-120']} @ 61-120</Badge>}
              {g.bands['121+'] > 0 && <Badge kind="121+">{g.bands['121+']} @ 121+</Badge>}
              <Badge kind="total">{g.tickets.length} total</Badge>
            </button>
            {isOpen(g, i) && (
              <div className="max-h-[28rem] overflow-auto border-t border-gray-800">
                <table className="w-full text-left text-xs text-gray-200">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr>
                      {HEAD.map((h) => (
                        <th key={h} className="px-3 py-2 font-semibold">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {g.tickets.map((t) => (
                      <tr key={t.ticket_id} className="border-t border-gray-800">
                        <td className="px-3 py-1.5">{t.ticket_id}</td>
                        <td className="px-3 py-1.5">{t.age_days}</td>
                        <td className="px-3 py-1.5">{t.client}</td>
                        <td className="px-3 py-1.5">{t.type ?? ''}</td>
                        <td className="px-3 py-1.5">{t.title}</td>
                        <td className="px-3 py-1.5">{t.status}</td>
                        <td className="px-3 py-1.5">{t.opened ?? ''}</td>
                        <td className="px-3 py-1.5">{t.last_activity ?? ''}</td>
                        <td className="px-3 py-1.5">{t.idle_days ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
