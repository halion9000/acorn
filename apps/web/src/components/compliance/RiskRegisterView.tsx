'use client';

/**
 * The risk register of the organization or of one of its clients: a Dashboard (counts by level and the likelihood by impact grid), the Register (a table; open a risk to change it, treat it and add tasks) and the
 * Archive (nothing is ever deleted). Starter risks come from a library of common ones, added one at a time.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress, useIsHomeClient } from '@/components/mssp/ClientPicker';
import { SecureframeRegisters } from './SecureframeRegisters';
import { RiskHeatMap } from './RiskHeatMap';
import { RiskLinks } from './RiskLinks';
import { saveText } from '@/lib/saveFile';
import { apiErrorDetail, downloadCsv, riskRegisterApi, type RiskDetail, type RiskInput, type RiskItem, type RiskLibraryItem, type RiskRegister } from '@/lib/api';

type Tab = 'dashboard' | 'register' | 'archive';
const LEVEL_CLASS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  high: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  medium: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
};
const TREATMENT_LABEL: Record<RiskItem['treatment'], string> = { mitigate: 'Mitigate', accept: 'Accept', transfer: 'Transfer', avoid: 'Avoid', undecided: 'Not decided' };

/** The colour of a grid cell: the level its likelihood times impact falls in (pure). */
export function cellLevel(likelihood: number, impact: number): 'critical' | 'high' | 'medium' | 'low' {
  const v = likelihood * impact;
  return v >= 16 ? 'critical' : v >= 10 ? 'high' : v >= 5 ? 'medium' : 'low';
}

function Badge({ level, value }: { level: string | null; value: number | null }) {
  if (!level || value === null) return <span className="text-gray-500">—</span>;
  return <span className={`inline-block min-w-[2rem] rounded border px-1.5 py-0.5 text-center text-xs font-semibold ${LEVEL_CLASS[level]}`}>{value}</span>;
}

function Dashboard({ data }: { data: RiskRegister }) {
  const s = data.summary;
  return (
    <div className="space-y-4" data-testid="risk-dashboard">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(['critical', 'high', 'medium', 'low'] as const).map((l) => (
          <div key={l} className={`rounded-lg border p-3 ${LEVEL_CLASS[l]}`}>
            <p className="text-2xl font-semibold" data-testid={`count-${l}`}>
              {s.by_level[l] ?? 0}
            </p>
            <p className="text-xs capitalize">{l} risks</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-gray-300">
        {s.total} risk{s.total === 1 ? '' : 's'}; {s.untreated} with no treatment decided;{(s.acceptance_expired ?? 0) > 0 ? <span className="text-red-300"> {s.acceptance_expired} accepted risk{s.acceptance_expired === 1 ? '' : 's'} past the end date;</span> : null} {s.open_tasks} open task{s.open_tasks === 1 ? '' : 's'}
        {s.overdue_tasks > 0 ? <span className="text-red-300"> ({s.overdue_tasks} overdue)</span> : null}.
      </p>
      <div>
        <p className="mb-1 text-xs uppercase text-gray-500">Likelihood (up) by impact (across), before treatment</p>
        <div className="inline-grid grid-cols-[auto_repeat(5,2.5rem)] gap-1 text-center text-xs" data-testid="risk-grid">
          {s.matrix.map((row, i) => (
            <div key={i} className="contents">
              <span className="self-center pr-1 text-gray-500">{5 - i}</span>
              {row.map((n, j) => (
                <span key={j} className={`flex h-10 items-center justify-center rounded border ${LEVEL_CLASS[cellLevel(5 - i, j + 1)]}`}>
                  {n > 0 ? n : ''}
                </span>
              ))}
            </div>
          ))}
          <span />
          {[1, 2, 3, 4, 5].map((n) => (
            <span key={n} className="text-gray-500">
              {n}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function ScalePick({ label, value, onChange, optional = false }: { label: string; value: number | null; onChange: (n: number | null) => void; optional?: boolean }) {
  return (
    <label className="text-xs text-gray-400">
      {label}
      <select
        aria-label={label}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className="mt-1 block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100"
      >
        {optional && <option value="">Not assessed</option>}
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );
}

function RiskForm({ categories, initial, onSave, onCancel }: { categories: string[]; initial: Partial<RiskItem>; onSave: (v: RiskInput) => Promise<void>; onCancel: () => void }) {
  const [v, setV] = useState({
    title: initial.title ?? '',
    description: initial.description ?? '',
    category: initial.category ?? 'Other',
    owner: initial.owner ?? '',
    likelihood: initial.likelihood ?? 3,
    impact: initial.impact ?? 3,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const field = 'mt-1 block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
  return (
    <form
      className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setErr('');
        try {
          await onSave({ ...v, owner: v.owner.trim() || null });
        } catch (x) {
          setErr(apiErrorDetail(x) ?? (x instanceof Error ? x.message : 'Could not save.'));
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="block text-xs text-gray-400">
        What could go wrong
        <input aria-label="Risk title" required minLength={3} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} className={field} />
      </label>
      <label className="block text-xs text-gray-400">
        Details
        <textarea aria-label="Risk details" rows={3} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} className={field} />
      </label>
      <div className="grid gap-3 sm:grid-cols-4">
        <label className="text-xs text-gray-400">
          Category
          <select aria-label="Category" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })} className={field}>
            {categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Owner
          <input aria-label="Owner" value={v.owner} onChange={(e) => setV({ ...v, owner: e.target.value })} className={field} />
        </label>
        <ScalePick label="Likelihood" value={v.likelihood} onChange={(n) => setV({ ...v, likelihood: n ?? 3 })} />
        <ScalePick label="Impact" value={v.impact} onChange={(n) => setV({ ...v, impact: n ?? 3 })} />
      </div>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-50">
          Save risk
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-300 hover:bg-gray-800">
          Cancel
        </button>
      </div>
    </form>
  );
}

function Detail({ clientId, risk, categories, onChange, onClose }: { clientId: string; risk: RiskDetail; categories: string[]; onChange: (r: RiskDetail) => void; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [task, setTask] = useState({ title: '', owner: '', due: '' });
  const [err, setErr] = useState('');
  const archived = risk.status === 'archived';
  const act = async (work: () => Promise<RiskDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (x) {
      setErr(apiErrorDetail(x) ?? (x instanceof Error ? x.message : 'That did not work.'));
    }
  };
  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
  return (
    <section className="space-y-4 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="risk-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-gray-500">{risk.ref}</p>
          <h3 className="text-lg font-semibold text-white">{risk.title}</h3>
          <p className="text-xs text-gray-400">
            {risk.category} · owner {risk.owner || 'not set'}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      {risk.description && <p className="whitespace-pre-wrap text-sm text-gray-300">{risk.description}</p>}
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {editing ? (
        <RiskForm
          categories={categories}
          initial={risk}
          onCancel={() => setEditing(false)}
          onSave={async (v) => {
            onChange(await riskRegisterApi.update(clientId, risk.id, v));
            setEditing(false);
          }}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-4 text-sm text-gray-300">
          <span>
            Before treatment <Badge level={risk.inherent_level} value={risk.inherent_score} /> ({risk.likelihood} x {risk.impact})
          </span>
          <span>
            After treatment <Badge level={risk.residual_level} value={risk.residual_score} />
            {risk.residual_score === null ? ' not assessed' : ` (${risk.residual_likelihood} x ${risk.residual_impact})`}
          </span>
          {!archived && (
            <button type="button" onClick={() => setEditing(true)} className="text-xs text-blue-300 hover:underline">
              Edit risk
            </button>
          )}
        </div>
      )}
      {!archived && (
        <div className="grid gap-3 sm:grid-cols-4" data-testid="treatment">
          <label className="text-xs text-gray-400">
            Treatment
            <select
              aria-label="Treatment"
              value={risk.treatment}
              onChange={(e) => void act(() => riskRegisterApi.update(clientId, risk.id, { treatment: e.target.value as RiskItem['treatment'] }))}
              className={`${field} mt-1 block w-full`}
            >
              {(Object.keys(TREATMENT_LABEL) as RiskItem['treatment'][]).map((t) => (
                <option key={t} value={t}>
                  {TREATMENT_LABEL[t]}
                </option>
              ))}
            </select>
          </label>
          {risk.treatment === 'accept' && (
            <label className="text-xs text-gray-400">
              Accepted until
              <input
                aria-label="Accepted until"
                type="date"
                defaultValue={risk.accepted_until ?? ''}
                onBlur={(e) => {
                  const next = e.target.value;
                  if (next !== (risk.accepted_until ?? '')) void act(() => riskRegisterApi.update(clientId, risk.id, next ? { accepted_until: next } : { clear_accepted_until: true }));
                }}
                className={`${field} mt-1 block w-full`}
              />
              {risk.acceptance_state === 'expired' && <span className="text-red-300" data-testid="acceptance-state">The acceptance ended. Decide again.</span>}
              {risk.acceptance_state === 'expiring' && <span className="text-amber-300" data-testid="acceptance-state">The acceptance ends soon.</span>}
            </label>
          )}
          <ScalePick
            label="Residual likelihood"
            optional
            value={risk.residual_likelihood}
            onChange={(n) => void act(() => (n === null ? riskRegisterApi.update(clientId, risk.id, { clear_residual: true }) : riskRegisterApi.update(clientId, risk.id, { residual_likelihood: n, residual_impact: risk.residual_impact ?? n })))}
          />
          <ScalePick
            label="Residual impact"
            optional
            value={risk.residual_impact}
            onChange={(n) => void act(() => (n === null ? riskRegisterApi.update(clientId, risk.id, { clear_residual: true }) : riskRegisterApi.update(clientId, risk.id, { residual_impact: n, residual_likelihood: risk.residual_likelihood ?? n })))}
          />
        </div>
      )}
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Tasks</h4>
        {risk.tasks.length === 0 && <p className="text-xs text-gray-500">No tasks yet.</p>}
        <ul className="space-y-1" data-testid="risk-tasks">
          {risk.tasks.map((t) => (
            <li key={t.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" aria-label={`Done: ${t.title}`} checked={t.done} disabled={archived} onChange={(e) => void act(() => riskRegisterApi.updateTask(clientId, risk.id, t.id, { done: e.target.checked }))} />
              <span className={t.done ? 'text-gray-500 line-through' : 'text-gray-200'}>{t.title}</span>
              <span className="text-xs text-gray-500">
                {t.owner || ''} {t.due_date ? `due ${t.due_date}` : ''}
              </span>
              {t.overdue && <span className="rounded bg-red-500/20 px-1.5 text-xs text-red-300">overdue</span>}
              {!archived && (
                <button type="button" aria-label={`Remove task: ${t.title}`} onClick={() => void act(() => riskRegisterApi.deleteTask(clientId, risk.id, t.id))} className="ml-auto text-xs text-gray-500 hover:text-red-300">
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        {!archived && (
          <form
            className="mt-2 flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!task.title.trim()) return;
              void act(() => riskRegisterApi.addTask(clientId, risk.id, { title: task.title, owner: task.owner.trim() || null, due_date: task.due || null }));
              setTask({ title: '', owner: '', due: '' });
            }}
          >
            <input aria-label="New task" placeholder="What has to be done" value={task.title} onChange={(e) => setTask({ ...task, title: e.target.value })} className={`${field} flex-1`} />
            <input aria-label="Task owner" placeholder="Owner" value={task.owner} onChange={(e) => setTask({ ...task, owner: e.target.value })} className={`${field} w-32`} />
            <input aria-label="Task due date" type="date" value={task.due} onChange={(e) => setTask({ ...task, due: e.target.value })} className={field} />
            <button type="submit" className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-200 hover:bg-gray-800">
              Add task
            </button>
          </form>
        )}
      </div>
      <RiskLinks clientId={clientId} risk={risk} archived={archived} onChange={onChange} />
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">History</h4>
        <ul className="max-h-40 space-y-0.5 overflow-y-auto text-xs text-gray-400" data-testid="risk-history">
          {risk.history.map((h, i) => (
            <li key={i}>
              {new Date(h.created_at).toISOString().slice(0, 16).replace('T', ' ')} · {h.actor || 'system'} · {h.action.replace(/_/g, ' ')}
              {h.detail ? `: ${h.detail}` : ''}
            </li>
          ))}
        </ul>
      </div>
      <div>
        {archived ? (
          <button type="button" onClick={() => void act(() => riskRegisterApi.restore(clientId, risk.id))} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-200 hover:bg-gray-800">
            Restore risk
          </button>
        ) : (
          <button type="button" onClick={() => void act(() => riskRegisterApi.archive(clientId, risk.id))} className="rounded border border-red-500/40 px-3 py-1 text-sm text-red-300 hover:bg-red-500/10">
            Archive risk
          </button>
        )}
      </div>
    </section>
  );
}

function Library({ clientId, onAdded, onClose }: { clientId: string; onAdded: (r: RiskDetail) => void; onClose: () => void }) {
  const [items, setItems] = useState<RiskLibraryItem[] | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let live = true;
    riskRegisterApi
      .library(clientId)
      .then((l) => live && setItems(l))
      .catch((e) => live && setErr(apiErrorDetail(e) ?? 'Could not load the library.'));
    return () => {
      live = false;
    };
  }, [clientId]);
  return (
    <section className="space-y-2 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="risk-library">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Common risks to start from</h3>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      {err && <p className="text-xs text-red-300">{err}</p>}
      <ul className="space-y-2">
        {(items ?? []).map((i) => (
          <li key={i.id} className="flex items-start justify-between gap-3 rounded border border-gray-800 p-2">
            <div>
              <p className="text-sm text-gray-100">{i.title}</p>
              <p className="text-xs text-gray-500">
                {i.category} · likelihood {i.likelihood} x impact {i.impact}
              </p>
              <p className="text-xs text-gray-400">{i.description}</p>
            </div>
            <button
              type="button"
              disabled={i.added}
              aria-label={`${i.added ? 'Added' : 'Add'}: ${i.title}`}
              onClick={async () => {
                try {
                  const r = await riskRegisterApi.fromLibrary(clientId, i.id);
                  setItems((all) => (all ?? []).map((x) => (x.id === i.id ? { ...x, added: true } : x)));
                  onAdded(r);
                } catch (e) {
                  setErr(apiErrorDetail(e) ?? 'Could not add it.');
                }
              }}
              className="shrink-0 rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:text-gray-600"
            >
              {i.added ? 'Added' : 'Add'}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RiskRegisterView() {
  const [clientId, setClientId] = useState('');
  const isHome = useIsHomeClient(clientId);
  const [tab, setTab] = useState<Tab>('dashboard');
  const [data, setData] = useState<RiskRegister | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<RiskDetail | null>(null);
  const [adding, setAdding] = useState(false);
  const [library, setLibrary] = useState(false);

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  const load = useCallback(async () => {
    setProblem('');
    try {
      setData(await riskRegisterApi.list(clientId, tab === 'archive'));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the register.'));
    }
  }, [clientId, tab]);

  useEffect(() => {
    setData(null);
    setOpen(null);
    void load();
  }, [load]);

  const choose = (id: string) => {
    setClientId(id);
  };
  const show = async (id: string) => {
    try {
      setOpen(await riskRegisterApi.get(clientId, id));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not open the risk.');
    }
  };
  const changed = (r: RiskDetail) => {
    setOpen(r);
    void load();
  };

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Risk register</h1>
        <p className="mt-1 text-sm text-gray-400">What could go wrong, how bad it would be, what was decided about it and who is doing what. Nothing is deleted: a risk is archived.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={choose} label="Whose risks" />
        </div>
      </div>
      {(!clientId || isHome) && <SecureframeRegisters show="risks" />}
      <div role="tablist" className="flex gap-1 border-b border-gray-800">
        {(['dashboard', 'register', 'archive'] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm capitalize ${tab === t ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
            {t}
          </button>
        ))}
        <span className="flex-1" />
        {tab !== 'archive' && (
          <div className="flex gap-2 pb-1">
            <button type="button" onClick={() => void downloadCsv('/api/v1/risk-register/export.csv', clientId).then((csv) => saveText('risks.csv', csv)).catch((e) => setProblem(apiErrorDetail(e) ?? 'Could not export.'))} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
              Export CSV
            </button>
            <button type="button" onClick={() => { setLibrary(true); setAdding(false); }} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
              Common risks
            </button>
            <button type="button" onClick={() => { setAdding(true); setLibrary(false); }} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
              Add risk
            </button>
          </div>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {adding && data && (
        <RiskForm
          categories={data.categories}
          initial={{}}
          onCancel={() => setAdding(false)}
          onSave={async (v) => {
            const made = await riskRegisterApi.create(clientId, v);
            setAdding(false);
            setOpen(made);
            await load();
          }}
        />
      )}
      {library && <Library clientId={clientId} onAdded={changed} onClose={() => setLibrary(false)} />}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && tab === 'dashboard' && <Dashboard data={data} />}
      {data && tab === 'dashboard' && <RiskHeatMap clientId={clientId} />}
      {data && tab !== 'dashboard' && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          {data.risks.length === 0 ? (
            <p className="p-4 text-sm text-gray-400" data-testid="risk-empty">
              {tab === 'archive' ? 'No archived risks.' : 'No risks yet. Add one, or start from the common risks.'}
            </p>
          ) : (
            <table className="w-full text-left text-sm" data-testid="risk-table">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Risk</th>
                  <th className="px-3 py-2">Owner</th>
                  <th className="px-3 py-2">Before</th>
                  <th className="px-3 py-2">Treatment</th>
                  <th className="px-3 py-2">After</th>
                  <th className="px-3 py-2">Tasks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {data.risks.map((r) => (
                  <tr key={r.id} className="cursor-pointer hover:bg-gray-800/40" onClick={() => void show(r.id)}>
                    <td className="px-3 py-2">
                      <button type="button" className="text-left text-blue-300 hover:underline" onClick={(e) => { e.stopPropagation(); void show(r.id); }}>
                        {r.title}
                      </button>
                      <div className="text-xs text-gray-500">
                        {r.ref} · {r.category}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-gray-300">{r.owner || '—'}</td>
                    <td className="px-3 py-2">
                      <Badge level={r.inherent_level} value={r.inherent_score} />
                    </td>
                    <td className="px-3 py-2 text-gray-300">{TREATMENT_LABEL[r.treatment]}</td>
                    <td className="px-3 py-2">
                      <Badge level={r.residual_level} value={r.residual_score} />
                    </td>
                    <td className="px-3 py-2 text-gray-300">{r.open_tasks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {open && data && <Detail clientId={clientId} risk={open} categories={data.categories} onChange={changed} onClose={() => setOpen(null)} />}
    </div>
  );
}
