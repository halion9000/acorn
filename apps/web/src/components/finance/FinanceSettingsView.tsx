'use client';

/**
 * Settings > Finance: the hourly cost A.C.O.R.N prices time with (the burdened rate: pay, payroll tax, benefits and 401k per hour). One default for anyone with no rate of their own, a rate per team, and a rate
 * per HaloPSA agent, which wins. Rates can be typed one at a time or pasted as "name, rate" lines; names are matched to the agents HaloPSA has and any that fit none or several are listed, not guessed.
 * Backed by /api/v1/finance/labor-rates. Profitability and Net income use these rates for direct labor.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';
import { ClientGroupsPanel } from './ClientGroupsPanel';
import { SoftwareCostsPanel } from './SoftwareCostsPanel';

export interface AgentRate {
  agent_id: string;
  name: string;
  team: string;
  active: boolean;
  rate: string | number;
  source: 'agent' | 'team' | 'default';
  own_rate: string | number | null;
}
export interface Overview {
  default_rate: string | number;
  teams: { team: string; rate: string | number }[];
  agents: AgentRate[];
  have_agents: boolean;
}

/** The name and rate lines in pasted text ("Alex Caico, 72.24", tab- or semicolon-separated also), blank lines and a header line skipped (pure). */
export function parseRateLines(text: string): { name: string; hourly_rate: string }[] {
  const out: { name: string; hourly_rate: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    // A tab or semicolon is the separator when there is one (so a rate such as 1,250.5 keeps its comma); otherwise the last comma.
    const cut = line.includes('\t') ? line.lastIndexOf('\t') : line.includes(';') ? line.lastIndexOf(';') : line.lastIndexOf(',');
    if (cut <= 0) continue;
    const name = line.slice(0, cut).trim().replace(/^"|"$/g, '');
    const rate = line.slice(cut + 1).trim().replace(/^"|"$/g, '');
    if (!name || !/^[$]?\s*-?[0-9][0-9,]*\.?[0-9]*$/.test(rate)) continue; // a header or a line with no rate
    out.push({ name, hourly_rate: rate });
  }
  return out;
}

const SOURCE_LABEL = { agent: 'their own rate', team: "their team's rate", default: 'the default rate' } as const;
const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const th = 'px-3 py-2 text-left';
const money = (v: string | number | null) => (v === null ? '' : `$${Number(v).toFixed(2)}`);

export function FinanceSettingsView() {
  const [data, setData] = useState<Overview | null>(null);
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortState | null>({ key: 'name', desc: false });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [defaultText, setDefaultText] = useState('');
  const [teamName, setTeamName] = useState('');
  const [teamText, setTeamText] = useState('');
  const [paste, setPaste] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/finance/labor-rates/overview');
      if (res.status === 403) return setDenied(true);
      if (!res.ok) return;
      const body = (await res.json()) as Overview;
      setData(body);
      setDefaultText(String(Number(body.default_rate).toFixed(2)));
    } catch {
      /* shows nothing */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const send = async (url: string, method: string, body?: unknown): Promise<Response | null> => {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const res = await authFetch(url, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!res.ok) {
        let why = '';
        try {
          const j = (await res.json()) as { detail?: unknown };
          why = typeof j.detail === 'string' ? j.detail : '';
        } catch {
          /* none given */
        }
        setProblem(why || (res.status === 403 ? 'You can read this but not change it.' : `That was not saved (${res.status}).`));
        return null;
      }
      return res;
    } catch {
      setProblem('That could not be sent.');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const saveRate = async (scope: 'agent' | 'team' | 'default', key: string, text: string) => {
    const n = Number(text.replace(/[$,]/g, ''));
    if (!Number.isFinite(n) || n < 0 || n > 10000) return setProblem('A rate is a number from 0 to 10,000 dollars an hour.');
    if (await send('/api/v1/finance/labor-rates', 'PUT', { scope, key, hourly_rate: n })) {
      setEdits((e) => {
        const { [key]: _gone, ...rest } = e;
        return rest;
      });
      await load();
    }
  };
  const clearRate = async (scope: 'agent' | 'team', key: string) => {
    if (await send(`/api/v1/finance/labor-rates?scope=${scope}&key=${encodeURIComponent(key)}`, 'DELETE')) await load();
  };
  const doImport = async () => {
    const rows = parseRateLines(paste);
    if (rows.length === 0) return setProblem('Paste lines of a name, then a comma, then the rate: Alex Caico, 72.24');
    const res = await send('/api/v1/finance/labor-rates/import', 'PUT', { rows });
    if (!res) return;
    const out = (await res.json()) as { saved: number; unmatched: string[] };
    setNote(`${out.saved} rate${out.saved === 1 ? '' : 's'} saved.${out.unmatched.length ? ` Not matched to one agent, so left out: ${out.unmatched.join(', ')}.` : ''}`);
    setPaste('');
    await load();
  };

  const agents = useMemo(() => (data ? sortedBy(data.agents, (a) => (sort ? ((a as unknown as Record<string, unknown>)[sort.key] as SortValue) : a.name), sort?.desc ?? false) : []), [data, sort]);

  if (denied) return <p className="p-6 text-sm text-gray-400">You do not have access to the finance settings.</p>;
  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Finance settings</h1>
        <p className="mt-1 text-sm text-gray-400">
          The hourly cost used to price time (pay, payroll tax, benefits and 401k per hour). A person&apos;s own rate wins, then their team&apos;s, then the default. Profitability and Net income use these for direct labor.
        </p>
      </div>
      {problem ? <p className="text-sm text-red-300" role="alert">{problem}</p> : null}
      {note ? <p className="text-sm text-emerald-300" data-testid="import-note">{note}</p> : null}
      {data === null ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {data ? (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-200">Default and teams</h2>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-gray-400" htmlFor="default-rate">Default rate ($ an hour)</label>
              <input id="default-rate" className={`${input} w-28`} value={defaultText} onChange={(e) => setDefaultText(e.target.value)} />
              <button type="button" className={ghost} disabled={busy} onClick={() => void saveRate('default', '', defaultText)}>Save default</button>
            </div>
            <ul className="space-y-1 text-sm text-gray-200">
              {data.teams.map((t) => (
                <li key={t.team} className="flex items-center gap-3">
                  <span className="w-48">{t.team}</span>
                  <span className="w-24 tabular-nums">{money(t.rate)}</span>
                  <button type="button" className={ghost} disabled={busy} onClick={() => void clearRate('team', t.team)}>Remove</button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <input className={`${input} w-48`} placeholder="Team name as in HaloPSA" value={teamName} onChange={(e) => setTeamName(e.target.value)} aria-label="Team name" />
              <input className={`${input} w-28`} placeholder="$ an hour" value={teamText} onChange={(e) => setTeamText(e.target.value)} aria-label="Team rate" />
              <button type="button" className={ghost} disabled={busy || !teamName.trim() || !teamText.trim()} onClick={() => void saveRate('team', teamName.trim(), teamText).then(() => { setTeamName(''); setTeamText(''); })}>Save team rate</button>
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-200">Import rates</h2>
            <p className="text-xs text-gray-500">One person a line: a name, a comma, the hourly rate. Names are matched to the agents HaloPSA has (a shortened first name with the same last name is the same person); any that fit none or several are listed, not guessed.</p>
            <textarea className={`${input} block w-full max-w-2xl`} rows={5} placeholder={'Alex Caico, 72.24\nBen Richard, 60.12'} value={paste} onChange={(e) => setPaste(e.target.value)} aria-label="Rates to import" />
            <button type="button" className={ghost} disabled={busy || !paste.trim()} onClick={() => void doImport()}>
              Import {parseRateLines(paste).length || ''} rates
            </button>
            {!data.have_agents ? <p className="text-xs text-amber-300">CORE has not sent the HaloPSA agents yet, so names cannot be matched until its next daily read.</p> : null}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-200">Each person</h2>
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-sm" data-testid="agent-rates">
                <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                  <tr>
                    <SortHeader label="Person" field="name" sort={sort} onSort={setSort} text className={th} />
                    <SortHeader label="Team" field="team" sort={sort} onSort={setSort} text className={th} />
                    <SortHeader label="Rate used" field="rate" sort={sort} onSort={setSort} className={th} />
                    <SortHeader label="From" field="source" sort={sort} onSort={setSort} text className={th} />
                    <SortHeader label="Their own rate" field="own_rate" sort={sort} onSort={setSort} className={th} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 text-gray-200">
                  {agents.map((a) => (
                    <tr key={a.agent_id} className={a.active ? '' : 'text-gray-500'}>
                      <td className="px-3 py-1.5">{a.name}{a.active ? '' : ' (left)'}</td>
                      <td className="px-3 py-1.5">{a.team || '—'}</td>
                      <td className="px-3 py-1.5 tabular-nums">{money(a.rate)}</td>
                      <td className="px-3 py-1.5 text-xs text-gray-400">{SOURCE_LABEL[a.source]}</td>
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-2">
                          <input
                            className={`${input} w-24`}
                            aria-label={`Rate for ${a.name}`}
                            value={edits[a.agent_id] ?? (a.own_rate === null ? '' : Number(a.own_rate).toFixed(2))}
                            onChange={(e) => setEdits({ ...edits, [a.agent_id]: e.target.value })}
                          />
                          <button type="button" className={ghost} disabled={busy || edits[a.agent_id] === undefined || !edits[a.agent_id]!.trim()} onClick={() => void saveRate('agent', a.agent_id, edits[a.agent_id]!)}>Save</button>
                          {a.own_rate !== null ? <button type="button" className={ghost} disabled={busy} onClick={() => void clearRate('agent', a.agent_id)}>Clear</button> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
      <SoftwareCostsPanel />
      <ClientGroupsPanel />
    </div>
  );
}
