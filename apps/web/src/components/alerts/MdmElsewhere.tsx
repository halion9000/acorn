'use client';

/** Alerts > Hidden: the clients whose MDM is managed by another tool. Addigy's "MDM is disabled" alert is hidden for each ticked client (kept, not deleted, and back when the client is un-ticked). */
import { useEffect, useMemo, useState } from 'react';

import { alertsApi, apiErrorDetail, type MdmClient } from '@/lib/api';

/** The clients that match what was typed, in any case (pure). */
export function filterClients(clients: MdmClient[], text: string): MdmClient[] {
  const needle = text.trim().toLowerCase();
  return needle ? clients.filter((c) => c.client_name.toLowerCase().includes(needle)) : clients;
}

export function MdmElsewhere() {
  const [clients, setClients] = useState<MdmClient[] | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [text, setText] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const out = await alertsApi.mdmClients();
        if (live && out?.clients) {
          setClients(out.clients);
          setTicked(new Set(out.clients.filter((c) => c.elsewhere).map((c) => c.client_id)));
        }
      } catch {
        /* the panel is simply not shown */
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const shown = useMemo(() => filterClients(clients ?? [], text), [clients, text]);
  if (!clients || clients.length === 0) return null;
  const was = new Set(clients.filter((c) => c.elsewhere).map((c) => c.client_id));
  const changed = ticked.size !== was.size || [...ticked].some((id) => !was.has(id));
  const toggle = (id: string) => setTicked((t) => (t.has(id) ? new Set([...t].filter((x) => x !== id)) : new Set([...t, id])));

  const save = async () => {
    setBusy(true);
    setNote('');
    try {
      const out = await alertsApi.setMdmClients([...ticked]);
      const n = out.clients.filter((c) => c.elsewhere).length;
      setClients(out.clients);
      setTicked(new Set(out.clients.filter((c) => c.elsewhere).map((c) => c.client_id)));
      setNote(`Saved: ${n} client${n === 1 ? '' : 's'} with their MDM managed elsewhere.`);
    } catch (e) {
      setNote(apiErrorDetail(e) ?? 'That did not save.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="mdm-elsewhere">
      <h2 className="text-sm font-semibold text-gray-200">Clients whose MDM is managed by another tool</h2>
      <p className="text-xs text-gray-500">
        Addigy shows MDM as disabled for a client that uses a different MDM. Tick those clients and Addigy&apos;s &quot;MDM is disabled&quot; alert is hidden for them, now and for new devices; every other alert of theirs is untouched. Un-tick a client to bring its alerts back.
      </p>
      <input aria-label="Find a client" placeholder="Find a client" value={text} onChange={(e) => setText(e.target.value)} className="block w-full max-w-sm rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" />
      <ul className="max-h-60 overflow-y-auto rounded border border-gray-800 p-2 text-sm text-gray-200">
        {shown.map((c) => (
          <li key={c.client_id}>
            <label className="flex items-center gap-2 py-0.5">
              <input type="checkbox" aria-label={c.client_name} checked={ticked.has(c.client_id)} onChange={() => toggle(c.client_id)} />
              <span>{c.client_name}</span>
              {c.hidden_alerts > 0 ? <span className="text-xs text-gray-500">({c.hidden_alerts} hidden now)</span> : null}
            </label>
          </li>
        ))}
        {shown.length === 0 ? <li className="text-xs text-gray-500">No client matches.</li> : null}
      </ul>
      <div className="flex items-center gap-3">
        <button type="button" disabled={busy || !changed} onClick={() => void save()} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
          Save
        </button>
        {note ? (
          <span className="text-xs text-gray-400" role="status">
            {note}
          </span>
        ) : null}
      </div>
    </section>
  );
}
