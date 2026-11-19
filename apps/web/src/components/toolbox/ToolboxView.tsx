'use client';

/**
 * The employee toolbox, stage 1 (roadmap rw-toolbox): pick a client, pick a Microsoft 365 tool, fill in what it needs, and ask. A request becomes an approval card; nothing runs against the client's tenant yet.
 */
import { useEffect, useRef, useState } from 'react';

import { PageHeader } from '@/components/ui/kit';
import { authFetch } from '@/lib/auth-session';
import { msspApi, type ChildTenant } from '@/lib/api';

export interface ToolInfo {
  id: string;
  group: string;
  label: string;
  risk: 'low' | 'medium' | 'high';
  reversible: boolean;
  summary: string;
  fields: FieldInfo[];
}
export interface FieldInfo {
  key: string;
  label: string;
  kind: 'user' | 'email' | 'users' | 'choice' | 'domain' | 'datetime' | 'text' | 'longtext' | 'group' | 'rules';
  options: string[];
  required: boolean;
  hint: string;
}
export interface Person {
  email: string;
  name: string;
  enabled: boolean;
  guest: boolean;
}
interface Lookups {
  people: Person[];
  domains: string[];
}
interface Catalog {
  groups: string[];
  tools: ToolInfo[];
  stage: string;
}

const INPUT = 'mt-1 block w-full max-w-md rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';

/** The text a person sees for one entry in a picker: the name, with a note when the account is switched off or is a guest. */
export function personLabel(p: Person): string {
  return `${p.name}${p.name === p.email ? '' : ` (${p.email})`}${p.enabled ? '' : ' - sign-in off'}${p.guest ? ' - guest' : ''}`;
}

/** Add one address to a comma list without repeating it. */
export function addToList(list: string, email: string): string {
  const have = list.split(',').map((x) => x.trim()).filter(Boolean);
  return have.includes(email) ? list : [...have, email].join(', ');
}

/** Take one address out of a comma list. */
export function removeFromList(list: string, email: string): string {
  return list.split(',').map((x) => x.trim()).filter((x) => x && x !== email).join(', ');
}

/** The lines of the confirmation: every value the person gave, labelled, in the form's order, leaving out what was left empty (pure). */
export function confirmLines(tool: ToolInfo, values: Record<string, string>): { label: string; value: string }[] {
  return tool.fields.filter((f) => (values[f.key] ?? '').trim() !== '').map((f) => ({ label: f.label, value: (values[f.key] ?? '').trim() }));
}

/** Whether a form is ready to send: a client is chosen and every required field has a value. */
export function isComplete(tool: ToolInfo | null, clientId: string, values: Record<string, string>): boolean {
  return tool !== null && clientId !== '' && tool.fields.every((f) => !f.required || (values[f.key] ?? '').trim() !== '');
}

function PeopleField({ f, value, onChange, people, listId }: { f: FieldInfo; value: string; onChange: (v: string) => void; people: Person[]; listId: string }) {
  const [draft, setDraft] = useState('');
  const chosen = value.split(',').map((x) => x.trim()).filter(Boolean);
  const add = () => {
    if (draft.trim()) onChange(addToList(value, draft.trim()));
    setDraft('');
  };
  return (
    <div className="mt-1 max-w-md">
      <div className="flex gap-2">
        <input aria-label={f.label} list={listId} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type a name, then pick" className={INPUT.replace('mt-1 ', '')} />
        <button type="button" onClick={add} disabled={!draft.trim()} className="rounded-md border border-gray-700 px-2 text-sm text-gray-200 disabled:opacity-50">
          Add
        </button>
      </div>
      <ul className="mt-1 flex flex-wrap gap-1">
        {chosen.map((c) => (
          <li key={c} className="rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-200">
            {c}{' '}
            <button type="button" aria-label={`Remove ${c}`} onClick={() => onChange(removeFromList(value, c))}>
              x
            </button>
          </li>
        ))}
      </ul>
      <datalist id={listId}>
        {people.map((p) => (
          <option key={p.email} value={p.email} label={personLabel(p)} />
        ))}
      </datalist>
    </div>
  );
}

export interface GroupData {
  groups: { name: string; kind: string; mail: string | null }[];
  groups_left_out?: number;
}
export interface RuleRow {
  name: string;
  rule_id: string | null;
  enabled: boolean | null;
  forwards_to: string | null;
  deletes: boolean;
  moves_to: string | null;
  suspicious: boolean;
  reasons: string[];
}
export interface RulesData {
  rules: RuleRow[];
}
/** What a read of CORE answer is at the moment: not asked, waiting for CORE, failed with a reason, or done with the data. */
export type Asked<T> = { state: 'idle' } | { state: 'loading' } | { state: 'failed'; message: string } | { state: 'done'; data: T };

const POLL_MS = 2000;
const POLL_TRIES = 45;

/** The rule names the person should have ticked when the list arrives: the ones that look bad, one name per line (pure). */
export function badRuleNames(rules: RuleRow[]): string {
  return rules.filter((r) => r.suspicious).map((r) => r.name).join('\n');
}

/** Tick or untick one rule in a value that holds one name per line (pure). */
export function toggleRule(value: string, name: string): string {
  const names = value.split('\n').map((n) => n.trim()).filter(Boolean);
  return (names.includes(name) ? names.filter((n) => n !== name) : [...names, name]).join('\n');
}

/**
 * Ask CORE for something read only (the client groups, a person inbox rules) and wait for the answer. ``key`` says what is being asked: while it is empty nothing is asked, and when it changes the
 * old answer is dropped. CORE answers within a few seconds to a minute, so this asks again every two seconds for up to 90 seconds.
 */
export function useCoreAnswer<T>(key: string, ask: Record<string, unknown> | null, kind: 'groups' | 'inbox-rules', onDone?: (data: T) => void): Asked<T> {
  const [res, setRes] = useState<{ key: string; value: Asked<T> } | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  useEffect(() => {
    if (!key || !ask) return;
    let live = true;
    const put = (value: Asked<T>) => {
      if (live) setRes({ key, value });
    };
    void (async () => {
      put({ state: 'loading' });
      try {
        const first = await authFetch(kind === 'groups' ? '/api/v1/toolbox/groups' : '/api/v1/toolbox/inbox-rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ask) });
        const body = (await first.json().catch(() => ({}))) as { detail?: string; request_id?: string; status?: string; result?: T; message?: string };
        if (!first.ok) return put({ state: 'failed', message: first.status === 403 ? 'You do not have the permission to ask for this.' : typeof body.detail === 'string' ? body.detail : 'It could not be asked for.' });
        let answer = body;
        for (let i = 0; i < POLL_TRIES && live && answer.status === 'waiting'; i++) {
          await new Promise((r) => setTimeout(r, POLL_MS));
          const again = await authFetch(kind === 'groups' ? `/api/v1/toolbox/groups/${body.request_id}` : `/api/v1/toolbox/inbox-rules/${body.request_id}`);
          if (!again.ok) return put({ state: 'failed', message: 'The answer could not be read.' });
          answer = (await again.json()) as typeof body;
        }
        if (!live) return;
        if (answer.status === 'done' && answer.result) {
          put({ state: 'done', data: answer.result });
          done.current?.(answer.result);
        } else if (answer.status === 'failed') put({ state: 'failed', message: answer.message ?? 'CORE could not read it.' });
        else put({ state: 'failed', message: 'CORE has not answered yet. Try again in a minute.' });
      } catch {
        put({ state: 'failed', message: 'It could not be asked for.' });
      }
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, kind]);
  return res && res.key === key ? res.value : { state: 'idle' };
}

function GroupField({ f, value, onChange, groups }: { f: FieldInfo; value: string; onChange: (v: string) => void; groups: Asked<GroupData> }) {
  const listId = `groups-${f.key}`;
  const list = groups.state === 'done' ? groups.data.groups : [];
  return (
    <div>
      <input aria-label={f.label} list={listId} value={value} onChange={(e) => onChange(e.target.value)} placeholder={groups.state === 'done' ? 'Type to find a group, then pick' : 'Group name'} className={INPUT} />
      <datalist id={listId}>
        {list.map((g) => (
          <option key={g.name} value={g.name} label={g.kind} />
        ))}
      </datalist>
      <p className="mt-0.5 text-xs text-gray-500" data-testid="groups-status">
        {groups.state === 'loading' ? 'Reading the groups of this client through CORE...' : null}
        {groups.state === 'done' ? `${list.length} groups.${groups.data.groups_left_out ? ` ${groups.data.groups_left_out} more were left out; type the name.` : ''}` : null}
        {groups.state === 'failed' ? `The groups could not be read: ${groups.message} Type the name instead.` : null}
        {groups.state === 'idle' ? 'Pick a client to see its groups.' : null}
      </p>
    </div>
  );
}

function RulesField({ f, value, onChange, rules, person }: { f: FieldInfo; value: string; onChange: (v: string) => void; rules: Asked<RulesData>; person: boolean }) {
  const chosen = new Set(value.split('\n').map((n) => n.trim()).filter(Boolean));
  return (
    <div className="mt-1 max-w-xl" role="group" aria-label={f.label}>
      {!person ? <p className="text-xs text-gray-500">Pick the mailbox above to see its rules.</p> : null}
      {rules.state === 'loading' ? <p className="text-xs text-gray-500">Reading the rules of this mailbox through CORE...</p> : null}
      {rules.state === 'failed' ? <p className="text-xs text-red-300">The rules could not be read: {rules.message}</p> : null}
      {rules.state === 'done' && rules.data.rules.length === 0 ? <p className="text-xs text-gray-400">This mailbox has no inbox rules.</p> : null}
      {rules.state === 'done' ? (
        <ul className="space-y-1">
          {rules.data.rules.map((r) => (
            <li key={`${r.rule_id ?? ''}${r.name}`} className={`rounded-md border p-2 text-sm ${r.suspicious ? 'border-red-500/50 bg-red-500/5' : 'border-gray-800'}`}>
              <label className="flex items-start gap-2 text-gray-200">
                <input type="checkbox" checked={chosen.has(r.name)} onChange={() => onChange(toggleRule(value, r.name))} className="mt-1" />
                <span className="min-w-0">
                  <span className="font-medium">{r.name}</span>
                  {r.enabled === false ? <span className="ml-2 text-xs text-gray-500">switched off</span> : null}
                  {r.reasons.length > 0 ? <span className={`block text-xs ${r.suspicious ? 'text-red-300' : 'text-gray-400'}`}>{r.reasons.join('; ')}</span> : <span className="block text-xs text-gray-500">An ordinary rule.</span>}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FieldControl({ f, value, onChange, lookups, groups, rules, person }: { f: FieldInfo; value: string; onChange: (v: string) => void; lookups: Lookups; groups: Asked<GroupData>; rules: Asked<RulesData>; person: boolean }) {
  if (f.kind === 'group') return <GroupField f={f} value={value} onChange={onChange} groups={groups} />;
  if (f.kind === 'rules') return <RulesField f={f} value={value} onChange={onChange} rules={rules} person={person} />;
  const listId = `people-${f.key}`;
  if (f.kind === 'user' || f.kind === 'email') {
    return (
      <>
        <input aria-label={f.label} list={listId} value={value} onChange={(e) => onChange(e.target.value)} placeholder={lookups.people.length ? 'Type a name, then pick' : 'Pick a client first'} className={INPUT} />
        <datalist id={listId}>
          {lookups.people.map((p) => (
            <option key={p.email} value={p.email} label={personLabel(p)} />
          ))}
        </datalist>
      </>
    );
  }
  if (f.kind === 'users') return <PeopleField f={f} value={value} onChange={onChange} people={lookups.people} listId={listId} />;
  if (f.kind === 'choice' || f.kind === 'domain') {
    const options = f.kind === 'domain' ? lookups.domains : f.options;
    return (
      <select aria-label={f.label} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT}>
        <option value="">{options.length || f.kind === 'choice' ? 'Choose' : 'Pick a client first'}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }
  if (f.kind === 'datetime') return <input aria-label={f.label} type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} />;
  if (f.kind === 'longtext') return <textarea aria-label={f.label} rows={3} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} />;
  return <input aria-label={f.label} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} />;
}

const RISK_TEXT: Record<ToolInfo['risk'], string> = { low: 'low risk', medium: 'medium risk', high: 'high risk' };
const RISK_CLASS: Record<ToolInfo['risk'], string> = { low: 'text-emerald-300', medium: 'text-amber-300', high: 'text-red-300' };

export function ToolboxView() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [clients, setClients] = useState<ChildTenant[]>([]);
  const [clientId, setClientId] = useState('');
  const [tool, setTool] = useState<ToolInfo | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [loaded, setLoaded] = useState<{ id: string; data: Lookups } | null>(null);
  const lookups: Lookups = loaded && loaded.id === clientId ? loaded.data : { people: [], domains: [] };

  useEffect(() => {
    void (async () => {
      try {
        const res = await authFetch('/api/v1/toolbox/tools');
        if (!res.ok) throw new Error(res.status === 403 ? 'The toolbox needs the alerts permission.' : `The API answered ${res.status}`);
        setCatalog((await res.json()) as Catalog);
        setClients(await msspApi.listChildren());
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load the toolbox.');
      }
    })();
  }, []);

  useEffect(() => {
    if (!clientId) return;
    let live = true;
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/toolbox/lookups?client_id=${encodeURIComponent(clientId)}`);
        if (res.ok && live) setLoaded({ id: clientId, data: (await res.json()) as Lookups });
      } catch {
        /* the pickers stay empty; the form still works with typed addresses */
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);

  const choose = (t: ToolInfo) => {
    setTool(t);
    setValues({});
    setMessage(null);
  };

  const send = async () => {
    if (!tool) return;
    setConfirming(false);
    setBusy(true);
    setMessage(null);
    try {
      const res = await authFetch('/api/v1/toolbox/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool: tool.id, client_id: clientId, args: values }) });
      const body = (await res.json().catch(() => ({}))) as { detail?: string; note?: string; title?: string };
      if (!res.ok) setMessage({ ok: false, text: typeof body.detail === 'string' ? body.detail : 'The request was not made.' });
      else {
        setMessage({ ok: true, text: `${body.title ?? 'Request'} was recorded. ${body.note ?? ''}`.trim() });
        setValues({});
      }
    } catch {
      setMessage({ ok: false, text: 'The request was not made. Try again.' });
    } finally {
      setBusy(false);
    }
  };

  const wantsGroups = tool !== null && clientId !== '' && tool.fields.some((f) => f.kind === 'group');
  const groups = useCoreAnswer<GroupData>(wantsGroups ? `groups:${clientId}` : '', wantsGroups ? { client_id: clientId } : null, 'groups');
  const personValue = (values.user ?? '').trim().toLowerCase();
  const personKnown = lookups.people.some((p) => p.email.toLowerCase() === personValue);
  const wantsRules = tool !== null && tool.fields.some((f) => f.kind === 'rules') && clientId !== '' && personKnown;
  const rules = useCoreAnswer<RulesData>(wantsRules ? `rules:${clientId}:${personValue}` : '', wantsRules ? { client_id: clientId, user: personValue } : null, 'inbox-rules', (d) =>
    setValues((cur) => ({ ...cur, rules: cur.rules ? cur.rules : badRuleNames(d.rules) })),
  );
  const complete = isComplete(tool, clientId, values);

  return (
    <div className="space-y-6 p-6" data-testid="toolbox">
      <PageHeader title="Toolbox" subtitle="Ask for a Microsoft 365 action for a client. Pressing Send request asks you to confirm first. The request is recorded; nothing runs against the client yet because running it through CIPP is the next stage." />
      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}
      <label className="block text-sm text-gray-300">
        Client
        <select aria-label="Client" value={clientId} onChange={(e) => {
            setClientId(e.target.value);
            setValues({});
          }} className="ml-2 rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100">
          <option value="">Pick a client</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      {catalog === null && !error && (
        <p role="status" className="text-sm text-gray-400">
          Loading…
        </p>
      )}
      {catalog?.groups.map((g) => (
        <section key={g} className="space-y-2" aria-label={g}>
          <h2 className="text-sm font-semibold text-white">{g}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {catalog.tools
              .filter((t) => t.group === g)
              .map((t) => (
                <button key={t.id} type="button" aria-pressed={tool?.id === t.id} onClick={() => choose(t)} className={`rounded-xl border p-3 text-left ${tool?.id === t.id ? 'border-blue-500 bg-blue-500/10' : 'border-gray-800 bg-gray-900 hover:bg-gray-800/60'}`}>
                  <p className="text-sm font-medium text-white">{t.label}</p>
                  <p className="mt-1 text-xs text-gray-400">{t.summary}</p>
                  <p className={`mt-1 text-[11px] ${RISK_CLASS[t.risk]}`}>
                    {RISK_TEXT[t.risk]}
                    {t.reversible ? '' : ', not easily reversed'}
                  </p>
                </button>
              ))}
          </div>
        </section>
      ))}
      {tool && (
        <section className="space-y-3 rounded-xl border border-gray-800 bg-gray-900 p-4" aria-label={`Ask for: ${tool.label}`}>
          <h2 className="text-sm font-semibold text-white">{tool.label}</h2>
          {tool.fields.map((f) => (
            <div key={f.key} className="block text-sm text-gray-300">
              <span>
                {f.label}
                {f.required ? '' : ' (optional)'}
              </span>
              <FieldControl f={f} value={values[f.key] ?? ''} onChange={(v) => setValues((cur) => ({ ...cur, [f.key]: v }))} lookups={lookups} groups={groups} rules={rules} person={personKnown} />
              {f.hint && <p className="mt-0.5 text-xs text-gray-500">{f.hint}</p>}
            </div>
          ))}
          <button type="button" disabled={!complete || busy} onClick={() => setConfirming(true)} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
            Send request
          </button>
          {message && (
            <p role={message.ok ? 'status' : 'alert'} className={`text-sm ${message.ok ? 'text-emerald-300' : 'text-red-300'}`}>
              {message.text}
            </p>
          )}
        </section>
      )}
      {confirming && tool ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div role="dialog" aria-modal="true" aria-label="Are you sure?" className="w-full max-w-md space-y-3 rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h2 className="text-base font-semibold text-white">Are you sure?</h2>
            <p className="text-sm text-gray-300">
              {tool.label} for <strong>{clients.find((c) => c.id === clientId)?.name ?? 'this client'}</strong>.
            </p>
            <dl className="space-y-1 text-sm">
              {confirmLines(tool, values).map((l) => (
                <div key={l.label} className="flex gap-2">
                  <dt className="text-gray-500">{l.label}:</dt>
                  <dd className="min-w-0 break-words text-gray-200">{l.value}</dd>
                </div>
              ))}
            </dl>
            <p className={`text-xs ${RISK_CLASS[tool.risk]}`}>
              {RISK_TEXT[tool.risk]}
              {tool.reversible ? '' : ', not easily reversed'}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" autoFocus onClick={() => setConfirming(false)} className="rounded-lg border border-gray-600 px-3 py-1.5 text-sm text-gray-200">
                Cancel
              </button>
              <button type="button" onClick={() => void send()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white">
                Yes, send it
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default ToolboxView;
