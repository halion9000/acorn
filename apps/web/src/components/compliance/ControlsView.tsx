'use client';

/**
 * Controls: every control of the frameworks that are turned on in one list, with how healthy each is (the same health as the Compliance overview). Unhealthy first; tabs for each health state with their counts, a
 * framework choice and a search. A control opens the framework page that holds its evidence.
 */
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress, useIsHomeClient } from '@/components/mssp/ClientPicker';
import { ControlGapReport } from './ControlGapReport';
import { SecureframeCard } from './SecureframeCard';
import { saveText } from '@/lib/saveFile';
import { apiErrorDetail, controlsApi, downloadCsv, type ControlList } from '@/lib/api';

type State = 'all' | 'unhealthy' | 'at_risk' | 'not_tested' | 'healthy';
export const STATE_LABEL: Record<Exclude<State, 'all'>, string> = { unhealthy: 'Unhealthy', at_risk: 'At risk', not_tested: 'Not tested', healthy: 'Healthy' };
const STATE_CLASS: Record<string, string> = {
  unhealthy: 'border-red-500/40 bg-red-500/15 text-red-300',
  at_risk: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  not_tested: 'border-gray-500/40 bg-gray-500/15 text-gray-300',
  healthy: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
};

/** The owner of one control: the name, or a link to name one; editing saves on Enter or when the box is left. */
function OwnerCell({ row, onSave }: { row: ControlList['rows'][number]; onSave: (owner: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(row.owner ?? '');
  const save = async () => {
    setEditing(false);
    if (text.trim() !== (row.owner ?? '')) await onSave(text.trim());
  };
  if (editing) {
    return (
      <input
        aria-label={`Owner of ${row.control_id}`}
        autoFocus
        maxLength={120}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void save();
          if (e.key === 'Escape') {
            setText(row.owner ?? '');
            setEditing(false);
          }
        }}
        className="w-36 rounded border border-gray-700 bg-gray-900 px-1.5 py-0.5 text-xs text-gray-100"
      />
    );
  }
  return (
    <button type="button" aria-label={`Set owner of ${row.control_id}`} onClick={() => { setText(row.owner ?? ''); setEditing(true); }} className={`text-xs hover:underline ${row.owner ? 'text-gray-200' : 'text-gray-500'}`}>
      {row.owner || 'Add owner'}
    </button>
  );
}

/** A small form under a control for adding a piece of evidence; it is saved as pending, to be accepted on the framework page. */
function AddEvidence({ row, onAdd, onClose }: { row: ControlList['rows'][number]; onAdd: (kind: 'attestation' | 'policy' | 'runbook' | 'log' | 'other', summary: string) => Promise<void>; onClose: () => void }) {
  const [kind, setKind] = useState<'attestation' | 'policy' | 'runbook' | 'log' | 'other'>('attestation');
  const [summary, setSummary] = useState('');
  const [busy, setBusy] = useState(false);
  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
  return (
    <form
      className="flex flex-wrap items-start gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await onAdd(kind, summary.trim());
        } finally {
          setBusy(false);
        }
      }}
    >
      <select aria-label={`Kind of evidence for ${row.control_id}`} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={field}>
        <option value="attestation">Attestation</option>
        <option value="policy">Policy</option>
        <option value="runbook">Runbook</option>
        <option value="log">Log</option>
        <option value="other">Other</option>
      </select>
      <textarea aria-label={`What the evidence for ${row.control_id} shows`} required minLength={5} rows={2} placeholder="What it shows, and where it is kept" value={summary} onChange={(e) => setSummary(e.target.value)} className={`${field} w-80`} />
      <button type="submit" disabled={busy || summary.trim().length < 5} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500 disabled:opacity-40">
        Save evidence
      </button>
      <button type="button" onClick={onClose} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
        Cancel
      </button>
    </form>
  );
}

export function ControlsView() {
  const [clientId, setClientId] = useState('');
  const isHome = useIsHomeClient(clientId);
  const [state, setState] = useState<State>('all');
  const [framework, setFramework] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [data, setData] = useState<ControlList | null>(null);
  const [problem, setProblem] = useState('');
  const [adding, setAdding] = useState<string | null>(null);
  const [added, setAdded] = useState('');

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    try {
      setData(await controlsApi.list(clientId, { framework, state: state === 'all' ? '' : state, q: debounced }));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the controls.'));
    }
  }, [clientId, framework, state, debounced]);
  useEffect(() => {
    void load();
  }, [load]);

  const all = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;
  const tab = (value: State, label: string, n?: number) => (
    <button key={value} role="tab" aria-selected={state === value} type="button" onClick={() => setState(value)} className={`px-3 py-1.5 text-sm ${state === value ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
      {label}
      {n !== undefined ? ` (${n})` : ''}
    </button>
  );
  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Controls</h1>
        <p className="mt-1 text-sm text-gray-400">Every control of the frameworks you turned on, and how healthy it is. A control is healthy when it has accepted evidence under a year old and none was rejected.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose controls" />
        </div>
      </div>
      {(!clientId || isHome) && <SecureframeCard />}
      <div role="tablist" className="flex flex-wrap items-center gap-1 border-b border-gray-800">
        {tab('all', 'All', data ? all : undefined)}
        {(Object.keys(STATE_LABEL) as Exclude<State, 'all'>[]).map((s) => tab(s, STATE_LABEL[s], data?.counts[s]))}
        <span className="flex-1" />
        <div className="flex items-center gap-2 pb-1">
          <select aria-label="Framework" value={framework} onChange={(e) => setFramework(e.target.value)} className={field}>
            <option value="">Frameworks that are on</option>
            {['SOC2', 'ISO27001', 'NIST-CSF', 'PCI-DSS', 'HIPAA', 'CIS-IG1'].map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
<button type="button" onClick={() => void downloadCsv('/api/v1/compliance/controls/export.csv', clientId, `framework=${encodeURIComponent(framework)}&state=${state === 'all' ? '' : state}&q=${encodeURIComponent(debounced)}`).then((csv) => saveText('controls.csv', csv)).catch((e) => setProblem(apiErrorDetail(e) ?? 'Could not export.'))} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
              Export CSV
            </button>
          <input aria-label="Search controls" placeholder="Search controls" value={search} onChange={(e) => setSearch(e.target.value)} className={`${field} w-56`} />
        </div>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {added && (
        <p role="status" className="text-sm text-emerald-300">
          {added}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && data.frameworks.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="controls-none-on">
          No framework is turned on. Turn one on in the Compliance overview, or choose one above to look at its controls anyway.
        </p>
      )}
      {data && data.frameworks.length > 0 && data.rows.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="controls-empty">
          No control matches.
        </p>
      )}
      {data && data.rows.length > 0 && <ControlGapReport rows={data.rows} />}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="controls-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Control</th>
                <th className="px-3 py-2">Framework</th>
                <th className="px-3 py-2">Health</th>
                <th className="px-3 py-2">Evidence</th>
                <th className="px-3 py-2">Owner</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.rows.flatMap((r) => [
                <tr key={`${r.framework}-${r.control_id}`} data-testid="control-row">
                  <td className="px-3 py-2">
                    <Link href={clientId ? `${r.link}?client=${encodeURIComponent(clientId)}` : r.link} className="text-blue-300 hover:underline">
                      {r.control_id}
                    </Link>
                    <div className="text-xs text-gray-400">{r.title}</div>
                    {r.group && <div className="text-xs text-gray-600">{r.group}</div>}
                  </td>
                  <td className="px-3 py-2 text-gray-300">{r.framework}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded border px-1.5 py-0.5 text-xs ${STATE_CLASS[r.state]}`}>{STATE_LABEL[r.state as Exclude<State, 'all'>]}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {r.accepted} accepted, {r.pending} pending, {r.rejected} rejected
                    {r.age_days !== null ? `; newest ${r.age_days} day${r.age_days === 1 ? '' : 's'} old` : ''}
                  </td>
                  <td className="px-3 py-2">
                    <OwnerCell row={r} onSave={(owner) => controlsApi.setOwner(clientId, r.framework, r.control_id, owner).then(() => load()).catch((e) => setProblem(apiErrorDetail(e) ?? 'Could not save the owner.'))} />
                  </td>
                  <td className="px-3 py-2">
                    <button type="button" aria-label={`Add evidence to ${r.control_id}`} onClick={() => setAdding(adding === `${r.framework}|${r.control_id}` ? null : `${r.framework}|${r.control_id}`)} className="text-xs text-blue-300 hover:underline">
                      Add evidence
                    </button>
                  </td>
                </tr>,
                ...(adding === `${r.framework}|${r.control_id}`
                  ? [
                      <tr key={`${r.framework}-${r.control_id}-add`} data-testid="add-evidence-row">
                        <td colSpan={6} className="bg-gray-900/40 px-3 py-3">
                          <AddEvidence
                            row={r}
                            onClose={() => setAdding(null)}
                            onAdd={(kind, summary) =>
                              controlsApi
                                .addEvidence(clientId, { framework: r.framework, control_id: r.control_id, control_title: r.title, evidence_kind: kind, summary })
                                .then(() => {
                                  setAdding(null);
                                  setAdded(`Evidence added to ${r.control_id}. It waits for review on the ${r.framework} page.`);
                                  return load();
                                })
                                .catch((e) => setProblem(apiErrorDetail(e) ?? 'Could not add the evidence.'))
                            }
                          />
                        </td>
                      </tr>,
                    ]
                  : []),
              ])}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > data.rows.length && (
        <p className="text-xs text-gray-500" data-testid="controls-cut">
          Showing the first {data.rows.length} of {data.total}. Narrow the list with a tab, a framework or a search.
        </p>
      )}
    </div>
  );
}
