'use client';

/**
 * Tests: how the client's own checks (read from its connected tools) answer each security practice. Each test says what it looked at, passes, fails, is only partly met, or is not tested (the client has none of the
 * tools it needs). "Record as evidence" writes the results as evidence for the controls of the frameworks that are on, so control health follows the live data.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, controlTestsApi, type TestSchedule, type ControlTests } from '@/lib/api';

type State = 'all' | 'fail' | 'partly' | 'pass' | 'not_tested';
export const STATE_LABEL: Record<Exclude<State, 'all'>, string> = { fail: 'Failing', partly: 'Partly met', pass: 'Passing', not_tested: 'Not tested' };
const STATE_CLASS: Record<string, string> = {
  fail: 'border-red-500/40 bg-red-500/15 text-red-300',
  partly: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  pass: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
  not_tested: 'border-gray-500/40 bg-gray-500/15 text-gray-300',
};

export function ControlTestsView() {
  const [clientId, setClientId] = useState('');
  const [state, setState] = useState<State>('all');
  const [data, setData] = useState<ControlTests | null>(null);
  const [problem, setProblem] = useState('');
  const [note, setNote] = useState('');
  const [schedule, setSchedule] = useState<TestSchedule | null>(null);
  const [busy, setBusy] = useState(false);
  const [showOff, setShowOff] = useState(false);

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const load = useCallback(async () => {
    try {
      setData(await controlTestsApi.list(clientId));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the tests.'));
    }
  }, [clientId]);
  useEffect(() => {
    setNote('');
    void load();
  }, [load]);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const s = await controlTestsApi.schedule(clientId);
        if (live && s) setSchedule(s);
      } catch {
        /* the switch is simply not shown */
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);
  const switchNightly = async (nightly: boolean) => {
    try {
      setSchedule(await controlTestsApi.saveSchedule(clientId, nightly));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not save that.'));
    }
  };

  const record = async () => {
    setBusy(true);
    try {
      const out = await controlTestsApi.record(clientId);
      setData(out.results);
      setNote(out.written === 0 ? 'Nothing to record: no framework that is on has a tested control, or no test has anything to go on yet.' : `Recorded ${out.written} piece${out.written === 1 ? '' : 's'} of evidence${out.replaced ? ` (replacing ${out.replaced} from the last time)` : ''}.`);
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not record.'));
    } finally {
      setBusy(false);
    }
  };

  const shown = (data?.results ?? []).filter((r) => (state === 'all' || r.state === state) && (showOff || r.enabled !== false));
  const off = (data?.results ?? []).filter((r) => r.enabled === false);
  const turn = async (id: string, on: boolean) => {
    const disabled = (data?.results ?? []).filter((r) => r.enabled === false && r.id !== id).map((r) => r.id);
    try {
      setData(await controlTestsApi.saveLibrary(clientId, on ? disabled : [...disabled, id]));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not save that.'));
    }
  };
  const tab = (value: State, label: string, n?: number) => (
    <button key={value} role="tab" aria-selected={state === value} type="button" onClick={() => setState(value)} className={`px-3 py-1.5 text-sm ${state === value ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
      {label}
      {n !== undefined ? ` (${n})` : ''}
    </button>
  );

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Tests</h1>
        <p className="mt-1 text-sm text-gray-400">
          Automated tests of security practices, worked out from the checks your connected tools already report. A test with none of the checks it needs is not tested: a tool the client does not use proves nothing either way.
        </p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose tests" />
        </div>
      </div>
      <div role="tablist" className="flex flex-wrap items-center gap-1 border-b border-gray-800">
        {tab('all', 'All', data ? data.results.length : undefined)}
        {(Object.keys(STATE_LABEL) as Exclude<State, 'all'>[]).map((s) => tab(s, STATE_LABEL[s], data?.counts[s]))}
        <span className="flex-1" />
        <button type="button" disabled={busy || !data} onClick={() => void record()} className="mb-1 rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500 disabled:opacity-40">
          Record as evidence
        </button>
      </div>
      {schedule && (
        <label className="flex flex-wrap items-center gap-2 text-sm text-gray-300" data-testid="tests-schedule">
          <input type="checkbox" checked={schedule.nightly} onChange={(e) => void switchNightly(e.target.checked)} />
          Record the results as evidence every night
          {schedule.last_run_at ? <span className="text-xs text-gray-500">Last run {new Date(schedule.last_run_at).toISOString().slice(0, 16).replace('T', ' ')} UTC. {schedule.last_result ?? ''}</span> : null}
        </label>
      )}
      {note && (
        <p role="status" className="text-sm text-emerald-300" data-testid="tests-note">
          {note}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && data.checks_held === 0 && (
        <p className="text-sm text-amber-300" data-testid="tests-no-checks">
          No checks have been read for this client yet, so every test is not tested.
        </p>
      )}
      {data && data.enabled.length === 0 && <p className="text-xs text-gray-500">No framework is turned on, so recording writes nothing. Turn one on in the Compliance overview.</p>}
      {off.length > 0 && (
        <label className="flex items-center gap-2 text-xs text-gray-400">
          <input type="checkbox" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} />
          Show the {off.length} test{off.length === 1 ? '' : 's'} turned off
        </label>
      )}
      <ul className="space-y-2" data-testid="tests-list">
        {shown.map((r) => (
          <li key={r.id} className={`rounded-lg border border-gray-800 bg-gray-900/40 p-3 ${r.enabled === false ? 'opacity-60' : ''}`} data-testid={`test-${r.id}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-medium text-white">{r.title}</p>
                <p className="text-xs text-gray-500">{r.why}</p>
              </div>
              <span className={`rounded border px-1.5 py-0.5 text-xs ${STATE_CLASS[r.state]}`}>
                {STATE_LABEL[r.state as Exclude<State, 'all'>]}
                {r.total > 0 ? `: ${r.met} of ${r.total} checks met` : ''}
              </span>
            </div>
            {r.checks.length > 0 && (
              <p className="mt-1 text-xs text-gray-400">
                {r.checks.map((c) => `${c.key.replace(/_/g, ' ')}: ${c.status.replace('_', ' ')}`).join(' · ')}
              </p>
            )}
            <label className="mt-1 flex items-center gap-2 text-xs text-gray-400">
              <input type="checkbox" aria-label={`Test ${r.title} is on`} checked={r.enabled !== false} onChange={(e) => void turn(r.id, e.target.checked)} />
              On (a test that is off is not counted and writes no evidence)
            </label>
            <p className="mt-1 text-xs text-gray-500">
              Answers: {r.controls.map((c) => `${c.framework} ${c.control_id}${c.on ? '' : ' (not on)'}`).join(', ')}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
