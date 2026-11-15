'use client';

/**
 * Audits: an audit of a framework and the evidence requests that come with it. Start one, add what the auditor asks for (or one request for each control that needs evidence), record who owns each, what was provided and
 * whether the auditor accepted it, and move the audit along. An audit cannot be completed while any request is open.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, auditsApi, type AuditDetail, type AuditList } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';
const STAGES = ['planning', 'fieldwork', 'review', 'complete'] as const;

function Detail({ clientId, audit, onChange, onClose }: { clientId: string; audit: AuditDetail; onChange: (a: AuditDetail) => void; onClose: () => void }) {
  const [err, setErr] = useState('');
  const [req, setReq] = useState({ title: '', owner: '', due: '' });
  const done = audit.status === 'complete';
  const act = async (work: () => Promise<AuditDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (e) {
      setErr(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };
  const next = STAGES[Math.min(STAGES.indexOf(audit.status as (typeof STAGES)[number]) + 1, STAGES.length - 1)]!;
  return (
    <section className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="audit-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">{audit.name}</h3>
          <p className="text-xs text-gray-400">
            {audit.framework} · {audit.auditor || 'auditor not set'} · {audit.status}
            {audit.period_start || audit.period_end ? ` · ${audit.period_start ?? '?'} to ${audit.period_end ?? '?'}` : ''}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      <p className="text-sm text-gray-300" data-testid="audit-progress">
        {audit.requests} requests: {audit.open} open ({audit.overdue} overdue), {audit.provided} provided, {audit.accepted} accepted.
      </p>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {!done && (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btn} onClick={() => void act(() => auditsApi.fromControls(clientId, audit.id))}>
            Add requests for the controls that need evidence
          </button>
          <button type="button" className={btn} onClick={() => void act(() => auditsApi.patch(clientId, audit.id, { status: next }))}>
            Move to {next}
          </button>
        </div>
      )}
      {!done && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const out = await auditsApi.addRequest(clientId, audit.id, { title: req.title.trim(), owner: req.owner.trim() || null, due_date: req.due || null });
              setReq({ title: '', owner: '', due: '' });
              return out;
            });
          }}
        >
          <input aria-label="Request" required minLength={3} placeholder="What the auditor asks for" value={req.title} onChange={(e) => setReq({ ...req, title: e.target.value })} className={`${field} w-72`} />
          <input aria-label="Owner" placeholder="Owner" value={req.owner} onChange={(e) => setReq({ ...req, owner: e.target.value })} className={`${field} w-36`} />
          <input aria-label="Due" type="date" value={req.due} onChange={(e) => setReq({ ...req, due: e.target.value })} className={field} />
          <button type="submit" className={btn}>
            Add request
          </button>
        </form>
      )}
      <ul className="space-y-2">
        {audit.items.map((r) => (
          <li key={r.id} className="rounded border border-gray-800 p-2 text-sm" data-testid="audit-request">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-gray-100">{r.title}</span>
              <span className={r.status === 'accepted' ? 'text-emerald-300' : r.status === 'provided' ? 'text-sky-300' : r.overdue ? 'text-red-300' : 'text-gray-300'}>
                {r.status}
                {r.overdue ? ' (overdue)' : ''}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              {r.owner ? `Owner ${r.owner}` : 'No owner'}
              {r.due_date ? ` · due ${r.due_date}` : ''}
              {r.link ? (
                <>
                  {' · '}
                  <a href={r.link} target="_blank" rel="noopener noreferrer" className="text-blue-300 hover:underline">
                    what was provided
                  </a>
                </>
              ) : null}
            </p>
            {!done && (
              <div className="mt-1 flex flex-wrap gap-2">
                {r.status === 'open' && (
                  <button type="button" aria-label={`Mark ${r.title} provided`} className={btn} onClick={() => void act(() => auditsApi.patchRequest(clientId, audit.id, r.id, { status: 'provided' }))}>
                    Mark provided
                  </button>
                )}
                {r.status === 'provided' && (
                  <button type="button" aria-label={`Accept ${r.title}`} className={btn} onClick={() => void act(() => auditsApi.patchRequest(clientId, audit.id, r.id, { status: 'accepted' }))}>
                    Accepted by the auditor
                  </button>
                )}
                {r.status !== 'open' && (
                  <button type="button" aria-label={`Reopen ${r.title}`} className={btn} onClick={() => void act(() => auditsApi.patchRequest(clientId, audit.id, r.id, { status: 'open' }))}>
                    Reopen
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
        {audit.items.length === 0 && <li className="text-xs text-gray-500">No requests yet.</li>}
      </ul>
    </section>
  );
}

export function AuditsView() {
  const [clientId, setClientId] = useState('');
  const [data, setData] = useState<AuditList | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<AuditDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [form, setForm] = useState({ name: '', framework: 'SOC2', auditor: '' });

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const load = useCallback(async () => {
    try {
      setData(await auditsApi.list(clientId));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the audits.'));
    }
  }, [clientId]);
  useEffect(() => {
    setOpen(null);
    void load();
  }, [load]);

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Audits</h1>
        <p className="mt-1 text-sm text-gray-400">Track an audit and what the auditor asks for. Your auditor does not sign in here yet: you record their requests and answers.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose audits" />
        </div>
      </div>
      <button type="button" onClick={() => setStarting((v) => !v)} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
        Start an audit
      </button>
      {starting && data && (
        <form
          className="flex flex-wrap items-end gap-2 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const made = await auditsApi.start(clientId, { name: form.name.trim(), framework: form.framework, auditor: form.auditor.trim() || null });
              setStarting(false);
              setForm({ name: '', framework: 'SOC2', auditor: '' });
              setOpen(made);
              await load();
            } catch (x) {
              setProblem(apiErrorDetail(x) ?? 'Could not start the audit.');
            }
          }}
        >
          <input aria-label="Name of the audit" required minLength={3} placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`${field} w-64`} />
          <select aria-label="Framework" value={form.framework} onChange={(e) => setForm({ ...form, framework: e.target.value })} className={field}>
            {data.frameworks.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
          <input aria-label="Auditor" placeholder="Auditor's firm" value={form.auditor} onChange={(e) => setForm({ ...form, auditor: e.target.value })} className={`${field} w-56`} />
          <button type="submit" className={btn}>
            Start
          </button>
        </form>
      )}
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && data.audits.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="audits-empty">
          No audits yet.
        </p>
      )}
      {data && data.audits.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="audits-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Audit</th>
                <th className="px-3 py-2">Framework</th>
                <th className="px-3 py-2">Auditor</th>
                <th className="px-3 py-2">Requests</th>
                <th className="px-3 py-2">Stage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.audits.map((a) => (
                <tr key={a.id} data-testid="audit-row">
                  <td className="px-3 py-2">
                    <button type="button" className="text-left text-blue-300 hover:underline" onClick={() => void auditsApi.get(clientId, a.id).then(setOpen).catch((e) => setProblem(apiErrorDetail(e) ?? 'Could not open the audit.'))}>
                      {a.name}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-gray-300">{a.framework}</td>
                  <td className="px-3 py-2 text-gray-300">{a.auditor ?? '—'}</td>
                  <td className={`px-3 py-2 text-xs ${a.overdue > 0 ? 'text-red-300' : 'text-gray-400'}`}>
                    {a.accepted} of {a.requests} accepted{a.overdue > 0 ? `, ${a.overdue} overdue` : ''}
                  </td>
                  <td className="px-3 py-2 text-gray-300 capitalize">{a.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <Detail clientId={clientId} audit={open} onChange={(a) => { setOpen(a); void load(); }} onClose={() => setOpen(null)} />}
    </div>
  );
}
