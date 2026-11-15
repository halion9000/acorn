'use client';

/**
 * Security questionnaires: paste a customer's questions and each is drafted from the answer library when at least half its words line up. A draft is not an answer until a person approves it; a question with no good
 * match stays blank. Approved answers can be kept in the library for next time. The questionnaire is completed when every question is approved, and exported as CSV.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, questionnairesApi, type LibraryAnswer, type QuestionnaireDetail, type QuestionnaireList } from '@/lib/api';

type Tab = 'questionnaires' | 'library';

/** Hand a text to the browser as a file to save. */
function downloadText(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';

function ItemRow({ clientId, q, item, onChange }: { clientId: string; q: QuestionnaireDetail; item: QuestionnaireDetail['items'][number]; onChange: (d: QuestionnaireDetail) => void }) {
  const [text, setText] = useState(item.answer);
  const [err, setErr] = useState('');
  useEffect(() => setText(item.answer), [item.answer]);
  const done = q.status === 'complete';
  const act = async (work: () => Promise<QuestionnaireDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (e) {
      setErr(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };
  const label = item.approved ? 'Approved' : item.answer.trim() ? (item.source === 'library' ? `Drafted from the library (${item.match_score}% of the words)` : 'Typed, not approved') : 'No answer yet';
  return (
    <li className="space-y-1 rounded border border-gray-800 p-3" data-testid="item-row">
      <p className="text-sm text-gray-100">
        {item.position}. {item.question}
      </p>
      <p className={`text-xs ${item.approved ? 'text-emerald-300' : item.answer.trim() ? 'text-amber-300' : 'text-gray-500'}`}>{label}</p>
      <textarea aria-label={`Answer to question ${item.position}`} rows={2} disabled={done} value={text} onChange={(e) => setText(e.target.value)} className={`${field} block w-full`} />
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {!done && (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btn} disabled={text.trim() === item.answer.trim()} onClick={() => void act(() => questionnairesApi.patchItem(clientId, q.id, item.id, { answer: text }))}>
            Save answer
          </button>
          <button type="button" className={btn} disabled={item.approved || !item.answer.trim() || text.trim() !== item.answer.trim()} onClick={() => void act(() => questionnairesApi.patchItem(clientId, q.id, item.id, { approved: true }))}>
            Approve
          </button>
          <button type="button" className={btn} disabled={!item.answer.trim() || item.source === 'library'} onClick={() => void act(() => questionnairesApi.patchItem(clientId, q.id, item.id, { save_to_library: true }))}>
            Keep in the library
          </button>
        </div>
      )}
    </li>
  );
}

function Library({ clientId, categories }: { clientId: string; categories: string[] }) {
  const [rows, setRows] = useState<LibraryAnswer[] | null>(null);
  const [form, setForm] = useState({ question: '', answer: '', category: 'General' });
  const [err, setErr] = useState('');
  const load = useCallback(async () => {
    try {
      setRows(await questionnairesApi.library(clientId));
    } catch (e) {
      setErr(apiErrorDetail(e) ?? 'Could not load the library.');
    }
  }, [clientId]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className="space-y-3" data-testid="library">
      <form
        className="space-y-2 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await questionnairesApi.addLibrary(clientId, form);
            setForm({ question: '', answer: '', category: 'General' });
            await load();
          } catch (x) {
            setErr(apiErrorDetail(x) ?? 'Could not add that.');
          }
        }}
      >
        <input aria-label="Library question" required minLength={3} placeholder="A question customers ask" value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} className={`${field} block w-full`} />
        <textarea aria-label="Library answer" required rows={2} placeholder="The answer to give" value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} className={`${field} block w-full`} />
        <div className="flex gap-2">
          <select aria-label="Library category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className={field}>
            {categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <button type="submit" className={btn}>
            Add to the library
          </button>
        </div>
      </form>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {rows && rows.length === 0 && <p className="text-sm text-gray-400">The library is empty. Add answers here, or keep an approved answer from a questionnaire.</p>}
      <ul className="space-y-2">
        {(rows ?? []).map((a) => (
          <li key={a.id} className="rounded border border-gray-800 p-3 text-sm" data-testid="library-row">
            <p className="text-gray-100">{a.question}</p>
            <p className="whitespace-pre-wrap text-gray-300">{a.answer}</p>
            <p className="mt-1 flex items-center gap-3 text-xs text-gray-500">
              {a.category}
              {a.last_reviewed ? ` · confirmed ${a.last_reviewed}` : ''}
              <button type="button" className="text-blue-300 hover:underline" onClick={() => void questionnairesApi.patchLibrary(clientId, a.id, { confirm: true }).then(load)}>
                Still true
              </button>
              <button type="button" className="text-gray-400 hover:text-red-300" aria-label={`Remove ${a.question}`} onClick={() => void questionnairesApi.removeLibrary(clientId, a.id).then(load)}>
                Remove
              </button>
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function QuestionnairesView() {
  const [clientId, setClientId] = useState('');
  const [tab, setTab] = useState<Tab>('questionnaires');
  const [data, setData] = useState<QuestionnaireList | null>(null);
  const [open, setOpen] = useState<QuestionnaireDetail | null>(null);
  const [problem, setProblem] = useState('');
  const [starting, setStarting] = useState(false);
  const [form, setForm] = useState({ name: '', customer: '', due: '', questions: '' });

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const load = useCallback(async () => {
    try {
      setData(await questionnairesApi.list(clientId));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the questionnaires.'));
    }
  }, [clientId]);
  useEffect(() => {
    setOpen(null);
    void load();
  }, [load]);

  const changed = (d: QuestionnaireDetail) => {
    setOpen(d);
    void load();
  };
  const fail = (e: unknown) => setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Questionnaires</h1>
        <p className="mt-1 text-sm text-gray-400">Answer a customer&apos;s security questionnaire from answers you have already given. Drafts are never sent until you approve them.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose questionnaires" />
        </div>
      </div>
      <div role="tablist" className="flex gap-1 border-b border-gray-800">
        <button role="tab" aria-selected={tab === 'questionnaires'} type="button" onClick={() => setTab('questionnaires')} className={`px-3 py-1.5 text-sm ${tab === 'questionnaires' ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400'}`}>
          Questionnaires
        </button>
        <button role="tab" aria-selected={tab === 'library'} type="button" onClick={() => setTab('library')} className={`px-3 py-1.5 text-sm ${tab === 'library' ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400'}`}>
          Answer library{data ? ` (${data.library_size})` : ''}
        </button>
        <span className="flex-1" />
        {tab === 'questionnaires' && (
          <button type="button" onClick={() => setStarting((v) => !v)} className="mb-1 rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
            Start a questionnaire
          </button>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {tab === 'library' && data && <Library clientId={clientId} categories={data.categories} />}
      {tab === 'questionnaires' && starting && (
        <form
          className="space-y-2 rounded-lg border border-gray-700 bg-gray-900/60 p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const made = await questionnairesApi.start(clientId, { name: form.name.trim(), customer: form.customer.trim() || null, due_date: form.due || null, questions: form.questions });
              setStarting(false);
              setForm({ name: '', customer: '', due: '', questions: '' });
              changed(made);
            } catch (x) {
              fail(x);
            }
          }}
        >
          <div className="grid gap-2 sm:grid-cols-3">
            <input aria-label="Name of the questionnaire" required minLength={3} placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={field} />
            <input aria-label="Customer" placeholder="Customer" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })} className={field} />
            <input aria-label="Due" type="date" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} className={field} />
          </div>
          <textarea aria-label="Questions" required rows={6} placeholder="Paste the questions, one to a line" value={form.questions} onChange={(e) => setForm({ ...form, questions: e.target.value })} className={`${field} block w-full`} />
          <button type="submit" className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500">
            Draft the answers
          </button>
        </form>
      )}
      {tab === 'questionnaires' && data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {tab === 'questionnaires' && data && data.questionnaires.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="questionnaires-empty">
          No questionnaires yet. Start one by pasting a customer&apos;s questions.
        </p>
      )}
      {tab === 'questionnaires' && data && data.questionnaires.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="questionnaires-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Questionnaire</th>
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Due</th>
                <th className="px-3 py-2">Progress</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.questionnaires.map((q) => (
                <tr key={q.id} data-testid="questionnaire-row">
                  <td className="px-3 py-2">
                    <button type="button" className="text-left text-blue-300 hover:underline" onClick={() => void questionnairesApi.get(clientId, q.id).then(setOpen).catch(fail)}>
                      {q.name}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-gray-300">{q.customer ?? '—'}</td>
                  <td className={`px-3 py-2 ${q.overdue ? 'text-red-300' : 'text-gray-300'}`}>{q.due_date ?? '—'}</td>
                  <td className="px-3 py-2 text-xs text-gray-400">
                    {q.approved} of {q.questions} approved; {q.drafted} drafted, {q.blank} blank
                  </td>
                  <td className="px-3 py-2 text-gray-300">{q.status === 'complete' ? 'Complete' : q.overdue ? 'Overdue' : 'Open'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === 'questionnaires' && open && (
        <section className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="questionnaire-detail">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-white">{open.name}</h3>
              <p className="text-xs text-gray-400" data-testid="questionnaire-progress">
                {open.approved} of {open.questions} approved; {open.drafted} drafted, {open.blank} blank
              </p>
            </div>
            <button type="button" onClick={() => setOpen(null)} className="text-xs text-gray-400 hover:text-gray-200">
              Close
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {open.status !== 'complete' && (
              <>
                <button type="button" className={btn} onClick={() => void questionnairesApi.approveDrafts(clientId, open.id).then(changed).catch(fail)}>
                  Approve the close matches
                </button>
                <button type="button" className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-40" disabled={open.approved < open.questions} onClick={() => void questionnairesApi.complete(clientId, open.id).then(changed).catch(fail)}>
                  Complete
                </button>
              </>
            )}
            <button type="button" className={btn} onClick={() => void questionnairesApi.exportCsv(clientId, open.id).then((csv) => downloadText(`${open.name.replace(/[^A-Za-z0-9._-]+/g, '-')}.csv`, csv)).catch(fail)}>
              Export CSV
            </button>
          </div>
          <ul className="space-y-2">
            {open.items.map((i) => (
              <ItemRow key={i.id} clientId={clientId} q={open} item={i} onChange={changed} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
