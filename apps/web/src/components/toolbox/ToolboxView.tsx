'use client';

/**
 * The employee toolbox, stage 1 (roadmap rw-toolbox): pick a client, pick a Microsoft 365 tool, fill in what it needs, and ask. A request becomes an approval card; nothing runs against the client's tenant yet.
 */
import { useEffect, useState } from 'react';

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
  fields: { key: string; label: string }[];
}
interface Catalog {
  groups: string[];
  tools: ToolInfo[];
  stage: string;
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

  const choose = (t: ToolInfo) => {
    setTool(t);
    setValues({});
    setMessage(null);
  };

  const send = async () => {
    if (!tool) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await authFetch('/api/v1/toolbox/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool: tool.id, client_id: clientId, args: values }) });
      const body = (await res.json().catch(() => ({}))) as { detail?: string; note?: string; title?: string };
      if (!res.ok) setMessage({ ok: false, text: typeof body.detail === 'string' ? body.detail : 'The request was not made.' });
      else {
        setMessage({ ok: true, text: `${body.title ?? 'Request'} is waiting for approval. ${body.note ?? ''}`.trim() });
        setValues({});
      }
    } catch {
      setMessage({ ok: false, text: 'The request was not made. Try again.' });
    } finally {
      setBusy(false);
    }
  };

  const complete = tool !== null && clientId !== '' && tool.fields.every((f) => (values[f.key] ?? '').trim() !== '');

  return (
    <div className="space-y-6 p-6" data-testid="toolbox">
      <PageHeader title="Toolbox" subtitle="Ask for a Microsoft 365 action for a client. Every press creates an approval request for a person to decide; nothing runs until a later stage connects approved requests to CIPP." />
      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}
      <label className="block text-sm text-gray-300">
        Client
        <select aria-label="Client" value={clientId} onChange={(e) => setClientId(e.target.value)} className="ml-2 rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100">
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
            <label key={f.key} className="block text-sm text-gray-300">
              {f.label}
              <input aria-label={f.label} value={values[f.key] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} className="mt-1 block w-full max-w-md rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100" />
            </label>
          ))}
          <button type="button" disabled={!complete || busy} onClick={() => void send()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
            Ask for approval
          </button>
          {message && (
            <p role={message.ok ? 'status' : 'alert'} className={`text-sm ${message.ok ? 'text-emerald-300' : 'text-red-300'}`}>
              {message.text}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export default ToolboxView;
