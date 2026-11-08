'use client';

/**
 * Settings > Profile: change your own password. The current password must be right, the new one is typed twice, and the server states the rule when it refuses one. When it works every session you hold ends
 * (this one too), so the next step is signing in again.
 */
import { useState } from 'react';
import { apiErrorDetail, passwordApi } from '@/lib/api';

const input = 'w-full rounded-md border border-gray-700 bg-gray-950/60 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600';

export function ChangePasswordCard() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const mismatch = again !== '' && next !== again;
  const ready = current !== '' && next !== '' && next === again && !busy;

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await passwordApi.change(current, next);
      setDone(r.detail);
      setCurrent('');
      setNext('');
      setAgain('');
    } catch (err) {
      setProblem(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : 'The password could not be changed.'));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="password-done">
        <h3 className="text-sm font-semibold text-gray-100">Password</h3>
        <p className="mt-2 text-sm text-emerald-300">{done}</p>
        <a href="/login" className="mt-3 inline-block rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-800">Sign in again</a>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-4">
      <h3 className="text-sm font-semibold text-gray-100">Password</h3>
      <p className="mt-1 text-xs text-gray-400">Changing it signs you out everywhere, this window included. You sign in again with the new one.</p>
      <div className="mt-3 grid max-w-sm gap-2">
        <label className="text-xs text-gray-400">
          Current password
          <input type="password" autoComplete="current-password" className={input} value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          New password
          <input type="password" autoComplete="new-password" className={input} value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          New password again
          <input type="password" autoComplete="new-password" className={input} value={again} onChange={(e) => setAgain(e.target.value)} />
        </label>
        {mismatch ? <p className="text-xs text-amber-300" data-testid="password-mismatch">The two new passwords are not the same.</p> : null}
        {problem ? <p className="text-xs text-red-300" data-testid="password-problem">{problem}</p> : null}
        <button type="button" disabled={!ready} onClick={() => void submit()} className="w-fit rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50">
          Change password
        </button>
      </div>
    </section>
  );
}
