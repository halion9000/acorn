'use client';

/**
 * vCIO Risk Scoring: a client's Business Review answered question by question and scored by risk, from Live Oak's scoring workbook. Pick a client, start or open an assessment, answer the
 * questions; the scorecard (overall, per category and section, the NIST CSF 2.0 reading and the gaps that lose the most points) is recomputed by the API on every answer. Each assessment is
 * kept, so a client's reviews can be compared over time. Backed by the API's vcio-risk-scoring routes.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiErrorDetail, msspApi, type ChildTenant } from '@/lib/api';
import { downloadCsv } from '@/lib/csv';
import {
  RATING_TEXT,
  assessmentCsv,
  autofillSentence,
  excludedFor,
  goodAnswer,
  keepQuestions,
  pct,
  vcioRiskApi,
  type QuestionFilter,
  type RiskAggregate,
  type RiskAssessment,
  type RiskAssessmentSummary,
  type RiskLibrary,
  type RiskPlatform,
  type RiskQuestion,
  type RiskRating,
  type RiskSeverity,
} from '@/lib/vcioRisk';

const input = 'rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const RATING_TEXT_CLASS: Record<RiskRating, string> = { green: 'text-emerald-300', amber: 'text-amber-300', red: 'text-red-300', na: 'text-gray-500' };
const RATING_BAR: Record<RiskRating, string> = { green: 'bg-emerald-500', amber: 'bg-amber-400', red: 'bg-red-500', na: 'bg-transparent' };
const SEVERITY_CLASS: Record<RiskSeverity, string> = {
  Critical: 'border-red-500/40 bg-red-500/10 text-red-300',
  High: 'border-orange-500/40 bg-orange-500/10 text-orange-300',
  Medium: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300',
  Low: 'border-blue-500/40 bg-blue-500/10 text-blue-300',
};
const PLATFORMS: { value: RiskPlatform; label: string }[] = [
  { value: 'm365', label: 'Microsoft 365' },
  { value: 'google', label: 'Google Workspace' },
  { value: 'both', label: 'Both' },
];
const FILTERS: { value: QuestionFilter; label: string }[] = [
  { value: 'all', label: 'All questions' },
  { value: 'open', label: 'Unanswered' },
  { value: 'gaps', label: 'Gaps (lost points)' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'auto', label: 'Filled in by the integrations' },
  { value: 'critical', label: 'Critical only' },
];
type Tab = 'scorecard' | 'questions' | 'method';
const TABS: { value: Tab; label: string }[] = [
  { value: 'scorecard', label: 'Scorecard' },
  { value: 'questions', label: 'Questions' },
  { value: 'method', label: 'Method' },
];
const OWN = 'own';

function Bar({ row, label, sub, flag }: { row: Pick<RiskAggregate, 'score' | 'rating'>; label: string; sub?: boolean; flag?: string }) {
  return (
    <div className={`flex items-center gap-3 ${sub ? 'pl-5 text-xs text-gray-400' : 'text-sm text-gray-100'}`} data-testid={sub ? 'risk-section' : 'risk-category'}>
      <div className={`${sub ? 'w-60' : 'w-64'} shrink-0 truncate`} title={label}>
        {label}
        {flag ? <span className="ml-1 text-red-300" title={flag}>⚑</span> : null}
      </div>
      <div className={`${sub ? 'h-1.5' : 'h-2.5'} flex-1 overflow-hidden rounded bg-gray-800`}>
        <div className={`h-full ${RATING_BAR[row.rating]}`} style={{ width: `${row.score === null ? 0 : Math.max(1, row.score * 100)}%` }} />
      </div>
      <div className={`w-12 shrink-0 text-right tabular-nums ${RATING_TEXT_CLASS[row.rating]}`}>{pct(row.score)}</div>
    </div>
  );
}

function Scorecard({ a, byId }: { a: RiskAssessment; byId: Map<string, RiskQuestion> }) {
  const c = a.scorecard;
  const capped = c.categories.filter((cat) => cat.critical_gaps > 0);
  const kpis: [string, string | number][] = [
    ['Answered', `${c.answered} of ${c.total}`],
    ['Unanswered', c.open],
    ['Unknown', c.unknown],
    ['Critical gaps', c.categories.reduce((n, cat) => n + cat.critical_gaps, 0)],
    ['Non-standard vendors', c.alternative_vendors],
  ];
  return (
    <div className="space-y-4" data-testid="risk-scorecard">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
        <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 sm:col-span-1">
          <div className="text-xs text-gray-400">Business Review overall</div>
          <div className={`text-3xl font-semibold ${RATING_TEXT_CLASS[c.rating]}`} data-testid="risk-overall">
            {pct(c.overall)}
          </div>
          <div className={`text-xs ${RATING_TEXT_CLASS[c.rating]}`}>{RATING_TEXT[c.rating]}</div>
        </div>
        {kpis.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
            <div className="text-xs text-gray-400">{label}</div>
            <div className="text-2xl font-semibold text-gray-100">{value}</div>
          </div>
        ))}
      </div>

      <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <h2 className="text-sm font-semibold text-white">By category</h2>
        {c.categories
          .filter((cat) => !cat.excluded)
          .map((cat) => (
            <div key={cat.name} className="space-y-1">
              <Bar row={cat} label={`${cat.name} (weight ${cat.weight})`} flag={cat.critical_gaps ? `${cat.critical_gaps} critical gap${cat.critical_gaps === 1 ? '' : 's'}: capped at ${pct(c.settings.cap)}` : undefined} />
              {cat.sections.map((s) => (
                <Bar key={s.name} row={s} label={s.name} sub />
              ))}
            </div>
          ))}
        <p className="pt-1 text-xs text-gray-500" data-testid="risk-cap-note">
          {capped.length > 0
            ? capped.map((cat) => `${cat.name}: ${cat.critical_gaps} critical gap${cat.critical_gaps === 1 ? '' : 's'}, capped at ${pct(c.settings.cap)}`).join(' · ')
            : 'No failed critical items.'}
        </p>
      </section>

      <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <h2 className="mb-2 text-sm font-semibold text-white">NIST CSF 2.0</h2>
        <div className="space-y-1">
          {c.csf.map((f) => (
            <div key={f.name} data-testid="risk-csf">
              <Bar row={f} label={f.questions === 0 ? `${f.name} (no questions)` : `${f.name} (${f.answered} of ${f.questions} answered)`} />
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <h2 className="mb-2 text-sm font-semibold text-white">
          Top gaps <span className="font-normal text-gray-500">({c.gaps.length} of {c.gap_count} answered items that lose points, worst first)</span>
        </h2>
        {c.gaps.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing answered loses points yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th scope="col" className="py-1 pr-3">Severity</th>
                <th scope="col" className="py-1 pr-3">Question</th>
                <th scope="col" className="py-1 pr-3">Answer</th>
                <th scope="col" className="py-1 text-right">Points lost</th>
              </tr>
            </thead>
            <tbody>
              {c.gaps.map((g) => {
                const q = byId.get(g.id);
                return (
                  <tr key={g.id} className="border-t border-gray-800 align-top" data-testid="risk-gap">
                    <td className="py-1.5 pr-3">
                      <span className={`rounded border px-1.5 py-0.5 text-xs ${SEVERITY_CLASS[g.severity]}`}>{g.severity}</span>
                    </td>
                    <td className="py-1.5 pr-3 text-gray-200">
                      {q?.text ?? g.id}
                      <span className="block text-xs text-gray-500">{q ? `${q.category} · ${q.subsection} · ${g.id}` : ''}</span>
                    </td>
                    <td className="py-1.5 pr-3 text-gray-300">{g.answer}</td>
                    <td className="py-1.5 text-right tabular-nums text-gray-100">{g.points_lost}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function QuestionRow({ q, a, library, busy, onAnswer, onSeverity }: { q: RiskQuestion; a: RiskAssessment; library: RiskLibrary; busy: boolean; onAnswer: (item: { id: string; answer?: string | null; vendor?: string | null; note?: string | null }) => void; onSeverity: (id: string, s: RiskSeverity) => void }) {
  const entry = a.answers[q.id] ?? {};
  const [vendor, setVendor] = useState(entry.vendor ?? '');
  const [note, setNote] = useState(entry.note ?? '');
  const [open, setOpen] = useState(Boolean(entry.note));
  useEffect(() => setVendor(entry.vendor ?? ''), [entry.vendor]);
  useEffect(() => setNote(entry.note ?? ''), [entry.note]);
  const severity = a.severity[q.id] ?? q.severity;
  const choices = q.type === 'vendor' ? library.vendor_answers : library.yesno_answers;
  const save = (over: { answer?: string | null; vendor?: string | null; note?: string | null }) =>
    onAnswer({ id: q.id, answer: entry.answer ?? null, vendor: vendor.trim() || null, note: note.trim() || null, ...over });
  return (
    <li className="rounded-lg border border-gray-800 bg-gray-900/50 p-3" data-testid="risk-question">
      <div className="flex flex-wrap items-start gap-2">
        <span className="mt-0.5 font-mono text-xs text-gray-500">{q.id}</span>
        <p className="min-w-0 flex-1 text-sm text-gray-100">{q.text}</p>
        <select
          aria-label={`Severity of ${q.id}`}
          value={severity}
          disabled={busy}
          onChange={(e) => onSeverity(q.id, e.target.value as RiskSeverity)}
          title={severity === q.severity ? 'How much this question weighs. Change it for this assessment if the risk is different here.' : `Changed for this assessment (the library says ${q.severity})`}
          className={`rounded border px-1.5 py-0.5 text-xs ${SEVERITY_CLASS[severity]}`}
        >
          {library.severities.map((s) => (
            <option key={s} value={s}>
              {s}
              {s !== q.severity || severity === q.severity ? '' : ' (library)'}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {choices.map((choice) => {
          const on = entry.answer === choice;
          const good = choice === goodAnswer(q);
          return (
            <button
              key={choice}
              type="button"
              disabled={busy}
              aria-pressed={on}
              onClick={() => save({ answer: on ? null : choice })}
              title={good ? 'The answer that earns the points' : undefined}
              className={`rounded border px-2 py-0.5 text-xs ${on ? (good ? 'border-emerald-500 bg-emerald-500/20 text-emerald-200' : choice === 'N/A' ? 'border-gray-500 bg-gray-700 text-gray-100' : 'border-amber-500 bg-amber-500/20 text-amber-200') : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`}
            >
              {choice}
            </button>
          );
        })}
        {q.type === 'vendor' && (
          <input
            aria-label={`Vendor or product in use for ${q.id}`}
            value={vendor}
            onChange={(e) => setVendor(e.target.value)}
            onBlur={() => (vendor.trim() || null) !== (entry.vendor ?? null) && save({ vendor: vendor.trim() || null })}
            placeholder={q.preferred ? `In use (preferred: ${q.preferred})` : 'Vendor / product in use'}
            className={`${input} ml-1 w-64 text-xs`}
          />
        )}
        {entry.source === 'auto' && (
          <span className="rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[11px] text-sky-300" data-testid="risk-auto" title="Filled in from the integrations, through the client's Client Review. Press another answer to set it yourself.">
            Auto
          </span>
        )}
        <button type="button" onClick={() => setOpen(!open)} className="ml-auto text-xs text-blue-300 hover:underline">
          {entry.note ? 'Note' : 'Add note'}
        </button>
        <span className="text-[11px] text-gray-500" title={q.csf_name}>
          {q.csf} · {q.csf_function}
        </span>
      </div>
      {entry.source === 'auto' && entry.evidence ? (
        <p className="mt-1 text-xs text-gray-400" data-testid="risk-evidence">
          {entry.evidence}
        </p>
      ) : null}
      {open && (
        <textarea
          aria-label={`Evidence or notes for ${q.id}`}
          value={note}
          rows={2}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => (note.trim() || null) !== (entry.note ?? null) && save({ note: note.trim() || null })}
          placeholder="Evidence / notes"
          className={`${input} mt-2 w-full`}
        />
      )}
    </li>
  );
}

function Questions({ a, library, busy, onAnswer, onSeverity }: { a: RiskAssessment; library: RiskLibrary; busy: boolean; onAnswer: (item: { id: string; answer?: string | null; vendor?: string | null; note?: string | null }) => void; onSeverity: (id: string, s: RiskSeverity) => void }) {
  const [filter, setFilter] = useState<QuestionFilter>('all');
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');
  const kept = useMemo(() => keepQuestions(library.questions, a, { filter, category, search }), [library.questions, a, filter, category, search]);
  const groups = useMemo(() => {
    const out: { key: string; category: string; section: string; items: RiskQuestion[] }[] = [];
    for (const q of kept) {
      const key = `${q.category}|${q.subsection}`;
      const last = out[out.length - 1];
      if (last && last.key === key) last.items.push(q);
      else out.push({ key, category: q.category, section: q.subsection, items: [q] });
    }
    return out;
  }, [kept]);
  const categories = library.categories.filter((c) => !excludedFor({ category: c }, a.platform));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Which questions" value={filter} onChange={(e) => setFilter(e.target.value as QuestionFilter)} className={input}>
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className={input}>
          <option value="">Every category</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <input aria-label="Find a question" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a question" className={`${input} w-64`} />
        <span className="text-xs text-gray-500" data-testid="risk-question-count">
          {kept.length} question{kept.length === 1 ? '' : 's'}
        </span>
      </div>
      {kept.length === 0 && <p className="rounded-lg border border-gray-800 bg-gray-900/60 p-4 text-sm text-gray-400">No question matches.</p>}
      {groups.map((g) => (
        <section key={g.key} className="space-y-2">
          <h3 className="text-xs font-semibold uppercase text-gray-400">
            {g.category} · {g.section}
          </h3>
          <ul className="space-y-2">
            {g.items.map((q) => (
              <QuestionRow key={q.id} q={q} a={a} library={library} busy={busy} onAnswer={onAnswer} onSeverity={onSeverity} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Method() {
  const items: [string, string][] = [
    ['Risk weight', 'Each question has a severity set from impact × likelihood (the risk model in NIST SP 800-30): Critical = 10 points, High = 6, Medium = 3, Low = 1. A failed Critical item therefore moves the score ten times more than a failed Low item.'],
    ['Credit', 'The good answer earns 100% of the points, Partial 50%, the bad answer 0%. For questions where “Yes” is the risk (exposed RDP, end-of-life devices, users clicking phishing, local admin rights) the good answer is “No”. Unknown earns 0%: an unverified control is not an assured control, and it is counted separately so it can be chased. N/A and unanswered questions are removed from both points earned and points possible.'],
    ['Answers from the integrations', 'Fill from integrations answers every question the client’s Client Review can answer (NinjaOne, Huntress, ThreatMate, Liongard, CIPP and the other connected tools): a reading of “met” becomes the good answer, “partly” becomes Partial and “not met” the bad answer; a Tech Stack product is Preferred when it is the standard vendor and Alternative when it is not. Each such answer is marked Auto and shows what the tool saw. An answer set by hand is never replaced, and an Auto answer the tools no longer support is taken out.'],
    ['Tech Stack', 'Tech Stack is one category inside the Business Review (its own weight in Settings), with sections for network equipment, servers, security tools, cloud services and backup. Preferred vendor = 100%, Alternative (a capable, non-standard product) = 100% by default and counted as a standardisation opportunity, None = 0%.'],
    ['Roll-up', 'Section and category score = points earned ÷ points possible. If a category contains a failed or unknown Critical item it is capped at 84% (Red) so a single major gap cannot hide behind many passes. The overall score is the weighted average of category scores (weights under Settings > vCIO Risk Scoring, which only someone who may change settings can open); categories with nothing answered drop out.'],
    ['Platform', 'A Microsoft 365 client is not asked the Google Workspace questions, and a Google Workspace client is not asked the Microsoft 365 ones. Choose Both for a client that uses both.'],
    ['Ratings', 'Green ≥ 95%, Amber 85–94%, Red < 85%: the same bands as the vCIO Toolbox.'],
    ['NIST CSF 2.0 view', 'Every question is mapped to a CSF 2.0 function and category, giving a second read of the same answers for compliance-focused clients. The question set has no Respond-function questions (incident response plan, escalation, notification); that row shows “no questions”.'],
  ];
  return (
    <section className="space-y-3 rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="risk-method">
      <h2 className="text-sm font-semibold text-white">How the score is calculated</h2>
      {items.map(([title, text]) => (
        <p key={title} className="text-sm text-gray-300">
          <span className="font-semibold text-gray-100">{title}.</span> {text}
        </p>
      ))}
    </section>
  );
}

export function RiskScoringView() {
  const [clients, setClients] = useState<ChildTenant[]>([]);
  const [clientId, setClientId] = useState('');
  const [library, setLibrary] = useState<RiskLibrary | null>(null);
  const [list, setList] = useState<RiskAssessmentSummary[]>([]);
  const [current, setCurrent] = useState<RiskAssessment | null>(null);
  const [tab, setTab] = useState<Tab>('scorecard');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, setNotice] = useState('');
  const [fillOnStart, setFillOnStart] = useState(true);
  const [draft, setDraft] = useState<{ review_date: string; platform: RiskPlatform; assessor: string }>({ review_date: '', platform: 'm365', assessor: '' });

  const fail = (err: unknown, fallback: string) => setError(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : fallback));

  useEffect(() => {
    msspApi.listChildren().then((rows) => setClients([...rows].sort((x, y) => x.name.localeCompare(y.name)))).catch(() => setClients([]));
    vcioRiskApi.library().then(setLibrary).catch((err) => fail(err, 'The questions could not be loaded.'));
  }, []);

  const loadList = useCallback(async (id: string, open?: string) => {
    setError('');
    try {
      const rows = (await vcioRiskApi.list(id === OWN ? undefined : id)).items.filter((r) => id !== OWN || r.client_name === null);
      setList(rows);
      const pick = open ?? rows[0]?.id;
      setCurrent(pick ? await vcioRiskApi.get(pick) : null);
    } catch (err) {
      setList([]);
      setCurrent(null);
      fail(err, 'The assessments could not be loaded.');
    }
  }, []);

  useEffect(() => {
    if (clientId) void loadList(clientId);
    else {
      setList([]);
      setCurrent(null);
    }
  }, [clientId, loadList]);

  const byId = useMemo(() => new Map((library?.questions ?? []).map((q) => [q.id, q])), [library]);

  /** Every change goes to the API, and what it sends back (the answers with the new scorecard) replaces what is on the page. */
  const change = async (work: () => Promise<RiskAssessment>, fallback: string) => {
    setBusy(true);
    setError('');
    try {
      const next = await work();
      setCurrent(next);
      setList((rows) => rows.map((r) => (r.id === next.id ? { ...r, review_date: next.review_date, platform: next.platform, assessor: next.assessor, score: next.score, rating: next.rating, answered: next.answered } : r)));
    } catch (err) {
      fail(err, fallback);
    } finally {
      setBusy(false);
    }
  };

  const fill = async (id: string) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const done = await vcioRiskApi.autofill(id);
      setCurrent(done.assessment);
      setList((rows) => rows.map((r) => (r.id === done.assessment.id ? { ...r, score: done.assessment.score, rating: done.assessment.rating, answered: done.assessment.answered } : r)));
      setNotice(autofillSentence(done));
    } catch (err) {
      fail(err, 'The answers could not be filled in from the integrations.');
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const made = await vcioRiskApi.create({ client_id: clientId === OWN ? undefined : clientId, review_date: draft.review_date || undefined, platform: draft.platform, assessor: draft.assessor.trim() });
      setStarting(false);
      setTab('questions');
      await loadList(clientId, made.id);
      if (fillOnStart) await fill(made.id);
    } catch (err) {
      fail(err, 'The assessment could not be started.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await vcioRiskApi.remove(current.id);
      setConfirmDelete(false);
      await loadList(clientId);
    } catch (err) {
      fail(err, 'The assessment could not be deleted.');
    } finally {
      setBusy(false);
    }
  };

  const clientName = clientId === OWN ? 'Own organisation' : (clients.find((c) => c.id === clientId)?.name ?? '');

  return (
    <div className="space-y-4" data-testid="risk-scoring">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <select aria-label="Client" value={clientId} onChange={(e) => setClientId(e.target.value)} className={input}>
          <option value="">Choose a client</option>
          <option value={OWN}>Own organisation</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {clientId && list.length > 0 && (
          <select aria-label="Assessment" value={current?.id ?? ''} onChange={(e) => void loadList(clientId, e.target.value)} className={input}>
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.review_date} · {pct(r.score)} · {r.answered} answered{r.assessor ? ` · ${r.assessor}` : ''}
              </option>
            ))}
          </select>
        )}
        {clientId && (
          <button type="button" onClick={() => { setDraft({ review_date: new Date().toISOString().slice(0, 10), platform: current?.platform ?? 'm365', assessor: current?.assessor ?? '' }); setStarting(true); }} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500">
            New assessment
          </button>
        )}
        {current && library && (
          <>
            <button type="button" onClick={() => downloadCsv(`vcio-risk-scoring-${clientName.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase() || 'client'}-${current.review_date}.csv`, assessmentCsv(library.questions, current))} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
              Export CSV
            </button>
            <button type="button" disabled={busy} onClick={() => void fill(current.id)} title="Answer every question the client's Client Review can answer from the connected tools. An answer you set by hand is never replaced." className="rounded-md border border-sky-500/50 px-3 py-1.5 text-sm text-white hover:bg-sky-500/20 disabled:opacity-50">
              Fill from integrations
            </button>
            <button type="button" onClick={() => window.print()} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
              Print / PDF
            </button>
            <button type="button" onClick={() => setConfirmDelete(true)} className="rounded-md border border-red-500/50 px-3 py-1.5 text-sm text-red-200 hover:bg-red-500/20">
              Delete assessment
            </button>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </p>
      )}

      {notice && (
        <p role="status" className="rounded-lg border border-sky-500/40 bg-sky-500/10 p-3 text-sm text-sky-100" data-testid="risk-notice">
          {notice}
        </p>
      )}

      {!clientId && <p className="rounded-lg border border-gray-800 bg-gray-900/60 p-4 text-sm text-gray-400">Choose a client to see its risk-scored reviews or to start one.</p>}
      {clientId && !current && !error && (
        <p className="rounded-lg border border-gray-800 bg-gray-900/60 p-4 text-sm text-gray-400" data-testid="risk-none">
          No assessment for {clientName} yet. Press New assessment to start one.
        </p>
      )}

      {current && library && (
        <>
          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <div className="mr-auto">
              <div className="text-xs text-gray-400">Customer</div>
              <div className="text-base font-semibold text-white">{clientName}</div>
            </div>
            <label className="text-xs text-gray-400">
              Review date
              <input type="date" aria-label="Review date" value={current.review_date} disabled={busy} onChange={(e) => e.target.value && void change(() => vcioRiskApi.update(current.id, { review_date: e.target.value }), 'The date could not be saved.')} className={`${input} mt-1 block`} />
            </label>
            <label className="text-xs text-gray-400">
              Platform
              <select aria-label="Platform" value={current.platform} disabled={busy} onChange={(e) => void change(() => vcioRiskApi.update(current.id, { platform: e.target.value as RiskPlatform }), 'The platform could not be saved.')} className={`${input} mt-1 block`}>
                {PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-400">
              Assessor
              <input aria-label="Assessor" defaultValue={current.assessor} key={`${current.id}-${current.assessor}`} disabled={busy} onBlur={(e) => e.target.value.trim() !== current.assessor && void change(() => vcioRiskApi.update(current.id, { assessor: e.target.value.trim() }), 'The assessor could not be saved.')} className={`${input} mt-1 block`} />
            </label>
          </div>

          <div role="tablist" className="flex gap-1 border-b border-gray-800 print:hidden">
            {TABS.map((t) => (
              <button key={t.value} type="button" role="tab" aria-selected={tab === t.value} onClick={() => setTab(t.value)} className={`rounded-t-md px-3 py-1.5 text-sm ${tab === t.value ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'scorecard' && <Scorecard a={current} byId={byId} />}
          {tab === 'questions' && (
            <Questions
              a={current}
              library={library}
              busy={busy}
              onAnswer={(item) => void change(() => vcioRiskApi.answer(current.id, [item]), 'The answer could not be saved.')}
              onSeverity={(id, s) => void change(() => vcioRiskApi.update(current.id, { severity: { [id]: s } }), 'The severity could not be saved.')}
            />
          )}
          {tab === 'method' && <Method />}
        </>
      )}

      {starting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="New assessment" className="w-full max-w-md space-y-3 rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">New assessment for {clientName}</h3>
            <label className="block text-xs text-gray-400">
              Review date
              <input type="date" aria-label="New review date" value={draft.review_date} onChange={(e) => setDraft({ ...draft, review_date: e.target.value })} className={`${input} mt-1 block w-full`} />
            </label>
            <label className="block text-xs text-gray-400">
              Platform
              <select aria-label="New platform" value={draft.platform} onChange={(e) => setDraft({ ...draft, platform: e.target.value as RiskPlatform })} className={`${input} mt-1 block w-full`}>
                {PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-gray-400">
              Assessor
              <input aria-label="New assessor" value={draft.assessor} onChange={(e) => setDraft({ ...draft, assessor: e.target.value })} className={`${input} mt-1 block w-full`} />
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-200">
              <input type="checkbox" aria-label="Fill in what the integrations can answer" checked={fillOnStart} onChange={(e) => setFillOnStart(e.target.checked)} />
              Fill in what the integrations can answer
            </label>
            <p className="text-xs text-gray-500">Earlier assessments of this client stay as they are.</p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStarting(false)} disabled={busy} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300">
                Cancel
              </button>
              <button type="button" onClick={() => void start()} disabled={busy} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                Start
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && current && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Delete this assessment?" className="w-full max-w-md space-y-3 rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Delete this assessment?</h3>
            <p className="text-sm text-gray-300">
              The {current.review_date} assessment of {clientName} ({current.answered} answers) is removed for good. This cannot be undone. It is written to the audit log.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmDelete(false)} disabled={busy} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300">
                No, keep it
              </button>
              <button type="button" onClick={() => void remove()} disabled={busy} className="rounded-md bg-red-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                Yes, delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
