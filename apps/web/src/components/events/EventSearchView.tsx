'use client';

/**
 * Event search (SIEM style storage): everything the sources reported and A.C.O.R.N kept as events, searched by client, source, kind, time range and text. Newest first, a page at a time; an event opens whole.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker } from '@/components/mssp/ClientPicker';
import { authFetch } from '@/lib/auth-session';

export interface EventRow {
  id: number;
  client_id: string | null;
  source: string;
  kind: string;
  event_time: string;
  pulled_at: string;
  external_id: string;
  preview: string;
}
interface Page {
  rows: EventRow[];
  next_before: number | null;
  sources: string[];
}

/** The search address for the filters given (pure): only the ones that are set. A time range given as dates covers whole days (the end day included). */
export function searchQuery(f: { client: string; source: string; kind: string; q: string; since: string; until: string; before?: number | null }): string {
  const p = new URLSearchParams();
  if (f.client) p.set('client_id', f.client);
  if (f.source) p.set('source', f.source);
  if (f.kind.trim()) p.set('kind', f.kind.trim());
  if (f.q.trim()) p.set('q', f.q.trim());
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.since)) p.set('since', `${f.since}T00:00:00Z`);
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.until)) {
    const end = new Date(`${f.until}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    p.set('until', end.toISOString().replace('.000Z', 'Z'));
  }
  if (f.before) p.set('before', String(f.before));
  return p.toString();
}

/** The address of the export for one client: the client and, when set, the source and the dates (pure; a client is required). */
export function exportQuery(f: { client: string; source: string; since: string; until: string }): string {
  const p = new URLSearchParams(searchQuery({ client: '', source: f.source, kind: '', q: '', since: f.since, until: f.until }));
  p.set('client_id', f.client);
  return p.toString();
}

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

export function EventSearchView() {
  const [client, setClient] = useState('');
  const [source, setSource] = useState('');
  const [kind, setKind] = useState('');
  const [q, setQ] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [rows, setRows] = useState<EventRow[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const [open, setOpen] = useState<{ id: number; text: string } | null>(null);

  const run = useCallback(
    async (more: boolean) => {
      setBusy(true);
      setProblem('');
      try {
        const res = await authFetch(`/api/v1/events/search?${searchQuery({ client, source, kind, q, since, until, before: more ? next : null })}`);
        if (res.status === 403) throw new Error('Searching events needs the reports permission.');
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const page = (await res.json()) as Page;
        setRows((old) => (more ? [...old, ...page.rows] : page.rows));
        setNext(page.next_before);
        setSources(page.sources);
        setSearched(true);
      } catch (e) {
        setProblem(e instanceof Error ? e.message : 'Could not search');
      } finally {
        setBusy(false);
      }
    },
    [client, source, kind, q, since, until, next],
  );
  useEffect(() => {
    void run(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exportZip = async (): Promise<void> => {
    setProblem('');
    try {
      const res = await authFetch(`/api/v1/events/export?${exportQuery({ client, source, since, until })}`);
      if (res.status === 403) throw new Error('Exporting needs the manage permission.');
      if (res.status === 413) throw new Error(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? 'That is too many events; choose a shorter date range.');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `events-${client.slice(0, 8)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not export');
    }
  };

  const show = async (row: EventRow): Promise<void> => {
    if (open?.id === row.id) return setOpen(null);
    try {
      const res = await authFetch(`/api/v1/events/${row.id}`);
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const full = (await res.json()) as { payload: unknown };
      setOpen({ id: row.id, text: JSON.stringify(full.payload, null, 2) });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not open the event');
    }
  };

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Event search</h1>
        <a href="/settings/event-retention" className="text-xs text-blue-300 hover:underline">
          Data retention
        </a>
        <p className="mt-1 text-sm text-gray-400">Everything the sources reported, kept as events and never changed. Search by client, source, kind, dates and text; open an event to see it whole.</p>
      </div>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(false);
        }}
      >
        <ClientPicker value={client} onChange={setClient} ownLabel="All clients" label="Client" />
        <label className="flex flex-col text-xs text-gray-400">
          Source
          <select aria-label="Source" className={field} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-400">
          Kind
          <input aria-label="Kind" className={field} placeholder="ticket.closed" value={kind} onChange={(e) => setKind(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-gray-400">
          From
          <input aria-label="From" type="date" className={field} value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-gray-400">
          To
          <input aria-label="To" type="date" className={field} value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <label className="flex min-w-[14rem] flex-1 flex-col text-xs text-gray-400">
          Text
          <input aria-label="Text" className={field} placeholder="anything in the event" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button type="submit" disabled={busy} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-100 hover:bg-gray-800 disabled:opacity-50">
          {busy ? 'Searching…' : 'Search'}
        </button>
        <button type="button" disabled={!client} title={client ? 'A zip of the events of this client with a manifest, for when the client asks' : 'Choose a client first'} onClick={() => void exportZip()} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-100 hover:bg-gray-800 disabled:opacity-50">
          Export this client
        </button>
      </form>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {searched && rows.length === 0 && !problem && <p className="text-sm text-gray-400" data-testid="no-events">No stored event matches. Events arrive as the sources are read; a new source starts from the day it was connected.</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="events-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">Event</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {rows.flatMap((r) => [
                <tr key={r.id} data-testid="event-row">
                  <td className="whitespace-nowrap px-3 py-1.5 text-gray-400">{r.event_time.replace('T', ' ').slice(0, 16)}</td>
                  <td className="px-3 py-1.5">{r.source}</td>
                  <td className="px-3 py-1.5">{r.kind}</td>
                  <td className="px-3 py-1.5">
                    <button type="button" className="text-left underline decoration-dotted hover:text-white" aria-expanded={open?.id === r.id} aria-label={`Open event ${r.external_id}`} onClick={() => void show(r)}>
                      {r.preview}
                    </button>
                  </td>
                </tr>,
                ...(open?.id === r.id
                  ? [
                      <tr key={`${r.id}-raw`} className="bg-gray-900/50" data-testid="event-raw">
                        <td colSpan={4} className="px-3 py-2">
                          <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs text-gray-300">{open.text}</pre>
                        </td>
                      </tr>,
                    ]
                  : []),
              ])}
            </tbody>
          </table>
        </div>
      )}
      {next !== null && (
        <button type="button" disabled={busy} onClick={() => void run(true)} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-100 hover:bg-gray-800 disabled:opacity-50">
          Older events
        </button>
      )}
    </div>
  );
}
