'use client';

/**
 * Access reviews: a periodic check that the people with access to a system should still have it. Start one for a system (the Microsoft 365 people, another tool's people, or names typed in), decide keep or
 * remove for each person (the ones worth a second look are flagged and listed first), and complete it when everyone is decided. Removing the access itself is done in the tool; this records the decision.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { accessReviewsApi, apiErrorDetail, type AccessReviewDetail, type AccessReviewList } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';

function Detail({ clientId, review, onChange, onClose }: { clientId: string; review: AccessReviewDetail; onChange: (r: AccessReviewDetail) => void; onClose: () => void }) {
  const [err, setErr] = useState('');
  const done = review.status === 'complete';
  const act = async (work: () => Promise<AccessReviewDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (e) {
      setErr(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };
  return (
    <section className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="review-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">{review.name}</h3>
          <p className="text-xs text-gray-400">
            {review.system} · reviewer {review.reviewer || 'not set'}
            {review.due_date ? ` · due ${review.due_date}${review.overdue ? ' (overdue)' : ''}` : ''}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      <p className="text-sm text-gray-300" data-testid="review-progress">
        {review.people} people: {review.keep} keep, {review.remove} remove, {review.pending} waiting for a decision. {review.flagged} flagged for a second look.
      </p>
      {done && <p className="text-sm text-emerald-300">Completed {review.completed_at?.slice(0, 10)} by {review.completed_by}. {review.summary}</p>}
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {!done && (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btn} disabled={review.pending === 0} onClick={() => void act(() => accessReviewsApi.decideAll(clientId, review.id, 'keep'))}>
            Keep everyone without a flag
          </button>
          <button type="button" className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-40" disabled={review.pending > 0} onClick={() => void act(() => accessReviewsApi.complete(clientId, review.id))}>
            Complete the review
          </button>
        </div>
      )}
      <table className="w-full text-left text-sm" data-testid="review-entries">
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="py-1">Person</th>
            <th className="py-1">Access</th>
            <th className="py-1">Decision</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {review.entries.map((e) => (
            <tr key={e.id} data-testid="review-entry">
              <td className="py-1.5">
                <div className="text-gray-100">{e.name || e.person}</div>
                {e.name && <div className="text-xs text-gray-500">{e.person}</div>}
                {e.flags.length > 0 && <div className="text-xs text-amber-300">{e.flags.join(', ')}</div>}
                {e.note && <div className="text-xs text-gray-500">{e.note}</div>}
              </td>
              <td className="py-1.5 text-xs text-gray-400">{e.access}</td>
              <td className="py-1.5">
                {done ? (
                  <span className={e.decision === 'remove' ? 'text-red-300' : 'text-emerald-300'}>{e.decision}</span>
                ) : (
                  <span className="flex gap-1">
                    <button type="button" aria-label={`Keep ${e.person}`} aria-pressed={e.decision === 'keep'} onClick={() => void act(() => accessReviewsApi.decide(clientId, review.id, e.id, 'keep'))} className={`${btn} ${e.decision === 'keep' ? 'bg-emerald-900/50' : ''}`}>
                      Keep
                    </button>
                    <button
                      type="button"
                      aria-label={`Remove ${e.person}`}
                      aria-pressed={e.decision === 'remove'}
                      onClick={() => {
                        const note = window.prompt(`Why should ${e.person} lose access? (optional)`) ?? '';
                        void act(() => accessReviewsApi.decide(clientId, review.id, e.id, 'remove', note));
                      }}
                      className={`${btn} ${e.decision === 'remove' ? 'bg-red-900/50' : ''}`}
                    >
                      Remove
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function AccessReviewsView() {
  const [clientId, setClientId] = useState('');
  const [data, setData] = useState<AccessReviewList | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<AccessReviewDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [form, setForm] = useState({ name: '', system: '', reviewer: '', due: '', people: '' });

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const load = useCallback(async () => {
    try {
      setData(await accessReviewsApi.list(clientId));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the reviews.'));
    }
  }, [clientId]);
  useEffect(() => {
    setOpen(null);
    void load();
  }, [load]);

  const show = async (id: string) => {
    try {
      setOpen(await accessReviewsApi.get(clientId, id));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not open the review.');
    }
  };
  const typed = !!data && !data.systems.some((s) => s.system === form.system);

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Access reviews</h1>
        <p className="mt-1 text-sm text-gray-400">Check, on a schedule, that the people who have access to a system should still have it. Decide keep or remove for each person and complete the review.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose reviews" />
        </div>
      </div>
      <div>
        <button type="button" onClick={() => setStarting((v) => !v)} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
          Start a review
        </button>
      </div>
      {starting && data && (
        <form
          className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const made = await accessReviewsApi.start(clientId, {
                name: form.name.trim(),
                system: form.system.trim(),
                reviewer: form.reviewer.trim() || null,
                due_date: form.due || null,
                people: typed ? form.people.split('\n') : [],
              });
              setStarting(false);
              setForm({ name: '', system: '', reviewer: '', due: '', people: '' });
              setOpen(made);
              await load();
            } catch (x) {
              setProblem(apiErrorDetail(x) ?? 'Could not start the review.');
            }
          }}
        >
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="text-xs text-gray-400">
              Name of the review
              <input aria-label="Name of the review" required minLength={3} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
            <label className="text-xs text-gray-400">
              System
              <input aria-label="System" required list="review-systems" value={form.system} onChange={(e) => setForm({ ...form, system: e.target.value })} className={`${field} mt-1 block w-full`} />
              <datalist id="review-systems">
                {data.systems.map((s) => (
                  <option key={s.system} value={s.system}>
                    {s.people} people
                  </option>
                ))}
              </datalist>
            </label>
            <label className="text-xs text-gray-400">
              Reviewer
              <input aria-label="Reviewer" value={form.reviewer} onChange={(e) => setForm({ ...form, reviewer: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
            <label className="text-xs text-gray-400">
              Due
              <input aria-label="Due" type="date" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
          </div>
          {typed && form.system.trim() !== '' && (
            <label className="block text-xs text-gray-400">
              A.C.O.R.N holds no people for this system. Type them, one name or address on each line
              <textarea aria-label="People" rows={4} value={form.people} onChange={(e) => setForm({ ...form, people: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
          )}
          <button type="submit" className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500">
            Take the snapshot and start
          </button>
        </form>
      )}
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && data.reviews.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="reviews-empty">
          No access reviews yet. Start one for a system whose access you want to check.
        </p>
      )}
      {data && data.reviews.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="reviews-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Review</th>
                <th className="px-3 py-2">System</th>
                <th className="px-3 py-2">Due</th>
                <th className="px-3 py-2">Progress</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.reviews.map((r) => (
                <tr key={r.id} data-testid="review-row">
                  <td className="px-3 py-2">
                    <button type="button" className="text-left text-blue-300 hover:underline" onClick={() => void show(r.id)}>
                      {r.name}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-gray-300">{r.system}</td>
                  <td className={`px-3 py-2 ${r.overdue ? 'text-red-300' : 'text-gray-300'}`}>{r.due_date ?? '—'}</td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {r.people - r.pending} of {r.people} decided
                  </td>
                  <td className="px-3 py-2 text-gray-300">{r.status === 'complete' ? 'Complete' : r.overdue ? 'Overdue' : 'Open'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <Detail clientId={clientId} review={open} onChange={(r) => { setOpen(r); void load(); }} onClose={() => setOpen(null)} />}
    </div>
  );
}
