'use client';

/**
 * Controls: every control of the frameworks that are turned on in one list, with how healthy each is (the same health as the Compliance overview). Unhealthy first; tabs for each health state with their counts, a
 * framework choice and a search. A control opens the framework page that holds its evidence.
 */
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, controlsApi, type ControlList } from '@/lib/api';

type State = 'all' | 'unhealthy' | 'at_risk' | 'not_tested' | 'healthy';
export const STATE_LABEL: Record<Exclude<State, 'all'>, string> = { unhealthy: 'Unhealthy', at_risk: 'At risk', not_tested: 'Not tested', healthy: 'Healthy' };
const STATE_CLASS: Record<string, string> = {
  unhealthy: 'border-red-500/40 bg-red-500/15 text-red-300',
  at_risk: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  not_tested: 'border-gray-500/40 bg-gray-500/15 text-gray-300',
  healthy: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
};

export function ControlsView() {
  const [clientId, setClientId] = useState('');
  const [state, setState] = useState<State>('all');
  const [framework, setFramework] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [data, setData] = useState<ControlList | null>(null);
  const [problem, setProblem] = useState('');

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
          <input aria-label="Search controls" placeholder="Search controls" value={search} onChange={(e) => setSearch(e.target.value)} className={`${field} w-56`} />
        </div>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
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
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="controls-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Control</th>
                <th className="px-3 py-2">Framework</th>
                <th className="px-3 py-2">Health</th>
                <th className="px-3 py-2">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.rows.map((r) => (
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
                </tr>
              ))}
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
