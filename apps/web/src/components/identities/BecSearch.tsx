'use client';

/**
 * Business email compromise (BEC) search for one person. Shown only to someone who holds the permission (the server checks it again) and only for a person Microsoft 365 knows. A press asks "Are you sure?",
 * then CORE has CIPP investigate the person (read only; usually a few minutes, up to half an hour or more when Microsoft's mail trace is slow). The list under the button follows each search live: Waiting for CORE, Running with its step, Done with the report, or
 * Failed with the reason. The report is shown as CIPP returned it, section by section; nothing is summarised as "clean" that CIPP did not say.
 */

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { authApi, identitiesApi, type BecCaseDetail, type BecCaseItem } from '@/lib/api';
import { safeDistance } from '@/lib/safe-date';

const STATUS_TEXT: Record<BecCaseItem['status'], { text: string; className: string }> = {
  pending: { text: 'Waiting for CORE', className: 'text-amber-300' },
  running: { text: 'Running', className: 'text-amber-300' },
  done: { text: 'Finished', className: 'text-emerald-300' },
  failed: { text: 'Failed', className: 'text-red-300' },
};

/** CIPP's own rating of a finished search and the checks that could not finish, from the summary A.C.O.R.N keeps. Only what CIPP gave: no rating and no list means nothing is shown (never "clean"). */
export function ratingOf(summary: Record<string, unknown> | null | undefined): { text: string; className: string; incomplete: string | null } | null {
  const level = typeof summary?.level === 'string' ? summary.level : '';
  const score = typeof summary?.score === 'number' ? summary.score : null;
  const missing = Array.isArray(summary?.incomplete) ? (summary!.incomplete as unknown[]).filter((x): x is string => typeof x === 'string') : [];
  if (!level && missing.length === 0) return null;
  const className = /^high$/i.test(level) ? 'text-red-300' : /^medium$/i.test(level) ? 'text-amber-300' : 'text-gray-400';
  return {
    text: level ? `CIPP rates it ${level}${score !== null ? ` (score ${score})` : ''}` : '',
    className,
    incomplete: missing.length > 0 ? `${missing.length} check${missing.length === 1 ? '' : 's'} could not finish: ${missing.join(', ')}` : null,
  };
}

/** When CORE had to cut CIPP's longest lists to keep the report, say which and how many were kept: "Sign-ins: first 100 of 3,000". Null when nothing was cut. Never hides that something was. */
export function shortenedNote(summary: Record<string, unknown> | null | undefined): string | null {
  const raw = Array.isArray(summary?.shortened) ? (summary!.shortened as unknown[]) : [];
  const parts = raw
    .map((x) => (x && typeof x === 'object' ? (x as Record<string, unknown>) : null))
    .filter((x): x is Record<string, unknown> => x !== null && typeof x.path === 'string' && typeof x.kept === 'number' && typeof x.total === 'number')
    .slice(0, 6)
    .map((x) => `${String(x.path)}: first ${(x.kept as number).toLocaleString('en-US')} of ${(x.total as number).toLocaleString('en-US')}`);
  if (parts.length === 0) return null;
  const more = raw.length > parts.length ? ` and ${raw.length - parts.length} more` : '';
  return `Some long lists were shortened to keep the report (${parts.join('; ')}${more}). The rest is unchanged.`;
}

export function canOfferBec(capabilities: string[] | undefined, knownTo: string[]): boolean {
  return (capabilities ?? []).includes('run_bec') && knownTo.includes('cipp');
}

/** "Mailbox rules" for MailboxRules / mailbox_rules: a readable name for a section key. */
export function sectionTitle(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** A text that is really a list or record written as JSON (CIPP sends the score breakdown that way) becomes that list or record; anything else is returned unchanged (pure). */
export function maybeParse(v: unknown): unknown {
  if (typeof v !== 'string') return v;
  const t = v.trim();
  if (!(t.startsWith('[') || t.startsWith('{'))) return v;
  try {
    return JSON.parse(t);
  } catch {
    return v;
  }
}

export interface ScoreSignal {
  signal: string;
  count: number;
  weight: number;
  applied: boolean;
  description: string;
}

/** CIPP's score for the mailbox, split into the signals that fired and the ones that were checked and found nothing (pure). Null when the report has no readable score. */
export function scoreOf(report: Record<string, unknown> | null | undefined): { level: string; value: number | null; fired: ScoreSignal[]; quiet: ScoreSignal[] } | null {
  const raw = report ? (report.Score ?? report.score) : undefined;
  if (!isRecord(raw)) return null;
  const parsed = maybeParse(raw.Breakdown ?? raw.breakdown);
  if (!Array.isArray(parsed)) return null;
  const signals: ScoreSignal[] = parsed.filter(isRecord).map((s) => ({
    signal: String(s.Signal ?? s.signal ?? ''),
    count: Number(s.Count ?? s.count ?? 0) || 0,
    weight: Number(s.Weight ?? s.weight ?? 0) || 0,
    applied: (s.Applied ?? s.applied) === true,
    description: String(s.Description ?? s.description ?? ''),
  }));
  const value = Number(raw.Value ?? raw.value);
  return { level: String(raw.Level ?? raw.level ?? ''), value: Number.isFinite(value) ? value : null, fired: signals.filter((s) => s.applied), quiet: signals.filter((s) => !s.applied) };
}

function ScoreSummary({ report }: { report: Record<string, unknown> }) {
  const score = scoreOf(report);
  if (!score) return null;
  return (
    <section className="rounded border border-gray-700 bg-gray-950 p-3" data-testid="bec-score-summary">
      <p className="text-sm font-medium text-gray-100">
        CIPP score: {score.level || 'not given'}
        {score.value !== null ? ` (${score.value})` : ''}
      </p>
      {score.fired.length === 0 ? (
        <p className="mt-1 text-xs text-gray-400">None of the {score.quiet.length} signals CIPP looks for fired.</p>
      ) : (
        <>
          <p className="mt-1 text-xs text-gray-400">
            {score.fired.length} signal{score.fired.length === 1 ? '' : 's'} fired. A signal firing is a reason to look, not proof of a takeover; weight is how much it adds to the score.
          </p>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="text-gray-500">
              <tr>
                <th scope="col" className="px-2 py-1 font-medium">What CIPP saw</th>
                <th scope="col" className="px-2 py-1 font-medium">How many</th>
                <th scope="col" className="px-2 py-1 font-medium">Weight</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {score.fired.map((s) => (
                <tr key={s.signal} data-testid={`signal-${s.signal}`}>
                  <td className="px-2 py-1 text-gray-200">
                    {s.description || sectionTitle(s.signal)}
                    <span className="ml-2 text-gray-500">({sectionTitle(s.signal)})</span>
                  </td>
                  <td className="px-2 py-1 text-gray-300">{s.count}</td>
                  <td className="px-2 py-1 text-gray-300">{s.weight}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {score.quiet.length > 0 ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-gray-400">Checked and found nothing ({score.quiet.length})</summary>
          <ul className="mt-1 list-disc pl-5 text-xs text-gray-400">
            {score.quiet.map((s) => (
              <li key={s.signal}>{s.description || sectionTitle(s.signal)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function cell(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** One section of the report: a list of records as a table, a record as rows, anything else as text. Long lists are cut with a count. */
export function Section({ name, value }: { name: string; value: unknown }) {
  const LIMIT = 50;
  let body: React.ReactNode;
  if (Array.isArray(value) && value.length === 0) body = <p className="text-xs text-gray-500">Nothing found.</p>;
  else if (Array.isArray(value) && value.every(isRecord)) {
    const rows = value as Record<string, unknown>[];
    const cols = [...new Set(rows.slice(0, LIMIT).flatMap((r) => Object.keys(r)))].slice(0, 8);
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-gray-500">
            <tr>
              {cols.map((c) => (
                <th key={c} className="whitespace-nowrap px-2 py-1 font-medium">
                  {sectionTitle(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {rows.slice(0, LIMIT).map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className="max-w-[18rem] break-words px-2 py-1 text-gray-300">
                    {cell(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > LIMIT && <p className="px-2 py-1 text-xs text-gray-500">Showing {LIMIT} of {rows.length}. Download the report for all of them.</p>}
      </div>
    );
  } else if (isRecord(value)) {
    // A value that is a list or record written as JSON text is shown as a section of its own, not as one long line.
    const entries = Object.entries(value).map(([k, v]) => [k, maybeParse(v)] as const);
    const plain = entries.filter(([, v]) => !(Array.isArray(v) || isRecord(v)));
    const nested = entries.filter(([, v]) => Array.isArray(v) || isRecord(v));
    body = (
      <div className="space-y-2">
        {plain.length > 0 ? (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
            {plain.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-gray-500">{sectionTitle(k)}</dt>
                <dd className="break-words text-gray-300">{cell(v)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {nested.map(([k, v]) => (
          <Section key={k} name={k} value={v} />
        ))}
      </div>
    );
  } else body = <p className="break-words text-xs text-gray-300">{cell(value)}</p>;
  return (
    <details className="rounded border border-gray-800 p-2" open={Array.isArray(value) ? value.length > 0 : true}>
      <summary className="cursor-pointer text-xs font-medium text-gray-200">
        {sectionTitle(name)}
        {Array.isArray(value) ? <span className="ml-2 text-gray-500">({value.length})</span> : null}
      </summary>
      <div className="mt-2">{body}</div>
    </details>
  );
}

function ReportWindow({ clientId, item, onClose }: { clientId: string; item: BecCaseItem; onClose: () => void }) {
  const { data, error } = useSWR<BecCaseDetail>(['bec-case', clientId, item.id], () => identitiesApi.becCase(clientId, item.id), { revalidateOnFocus: false });
  function download() {
    if (!data?.report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data.report, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${item.case_ref}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div role="dialog" aria-modal="true" aria-label={`Report ${item.case_ref}`} className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-100">
            {item.case_ref} <span className="text-sm font-normal text-gray-400">· {item.email}</span>
          </h3>
          <button type="button" onClick={onClose} aria-label="Close" className="text-gray-500 hover:text-gray-300">
            ✕
          </button>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto">
          {error ? <p className="text-sm text-red-300">Could not load the report.</p> : null}
          {!data && !error ? <p className="text-sm text-gray-500">Loading…</p> : null}
          {data && !data.report ? <p className="text-sm text-gray-400">{data.message ?? 'This search has no report.'}</p> : null}
          {data?.report ? (
            <>
              <p className="text-xs text-gray-500">As CIPP returned it. A section that is missing or empty is not a pass: check the data-source notes CIPP gives for checks that could not run.</p>
              <ScoreSummary report={data.report as Record<string, unknown>} />
              {Object.entries(data.report).map(([k, v]) => (
                <Section key={k} name={k} value={v} />
              ))}
            </>
          ) : null}
        </div>
        <div className="mt-3 flex justify-end gap-2">
          {data?.report ? (
            <button type="button" onClick={download} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
              Download JSON
            </button>
          ) : null}
          <button type="button" onClick={onClose} className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export function BecSearch({ clientId, email, knownTo }: { clientId: string; email: string; knownTo: string[] }) {
  const [cached, setCached] = useState<string[]>([]);
  useEffect(() => setCached(authApi.currentUser()?.capabilities ?? []), []);
  const { data: fresh } = useSWR('my-capabilities', () => authApi.freshCapabilities(), { revalidateOnFocus: false, dedupingInterval: 60_000, shouldRetryOnError: false });
  const allowed = canOfferBec(fresh ?? cached, knownTo);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [viewing, setViewing] = useState<BecCaseItem | null>(null);
  const { data, mutate } = useSWR(allowed ? ['bec-cases', clientId, email] : null, () => identitiesApi.becCases(clientId, email), {
    refreshInterval: (latest) => (latest?.items.some((i) => i.status === 'pending' || i.status === 'running') ? 5_000 : 0),
    revalidateOnFocus: false,
  });
  if (!allowed) return null;

  async function start() {
    setBusy(true);
    setProblem('');
    try {
      await identitiesApi.startBec({ client_id: clientId, email, confirm: true });
      setAsking(false);
      await mutate();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'The search was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="bec-search">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">Business email compromise</h4>
      <button
        type="button"
        onClick={() => {
          setProblem('');
          setAsking(true);
        }}
        className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800"
      >
        Run BEC search
      </button>
      <p className="mt-1 text-[11px] text-gray-500">CIPP checks rules, forwarding, consents, sign-ins and mail activity. Read only; usually a few minutes, but a slow mail trace can take half an hour or more.</p>
      {problem && !asking && <p className="mt-1 text-xs text-red-300">{problem}</p>}

      {(data?.items ?? []).length > 0 && (
        <ul className="mt-2 space-y-2" data-testid="bec-case-list">
          {data!.items.map((i) => (
            <li key={i.id} className="text-xs text-gray-300">
              <div>
                {i.case_ref} <span className={STATUS_TEXT[i.status].className}>{STATUS_TEXT[i.status].text}</span>
                <span className="text-gray-500"> · {safeDistance(i.created_at, { addSuffix: true })}</span>
                {i.status === 'done' && (
                  <button type="button" onClick={() => setViewing(i)} className="ml-2 text-blue-300 hover:text-blue-200">
                    View report
                  </button>
                )}
              </div>
              {i.status === 'done' && ratingOf(i.summary) ? (
                <div className="mt-0.5">
                  <span className={ratingOf(i.summary)!.className}>{ratingOf(i.summary)!.text}</span>
                  {ratingOf(i.summary)!.incomplete ? <span className="block text-gray-400">{ratingOf(i.summary)!.incomplete}</span> : null}
                </div>
              ) : null}
              {i.status === 'done' && shortenedNote(i.summary) ? <div className="mt-0.5 text-xs text-gray-400">{shortenedNote(i.summary)}</div> : null}
              {(i.status === 'running' || i.status === 'pending') && (
                <div className="mt-1">
                  {i.steps_total > 0 ? (
                    <div className="h-1.5 w-full overflow-hidden rounded bg-gray-800" role="progressbar" aria-valuemin={0} aria-valuemax={i.steps_total} aria-valuenow={i.step}>
                      <div className="h-full bg-amber-400" style={{ width: `${Math.min(100, Math.round((i.step / i.steps_total) * 100))}%` }} />
                    </div>
                  ) : null}
                  <span className="text-gray-500">
                    {i.steps_total > 0 ? `Step ${i.step} of ${i.steps_total}` : 'Working'}
                    {i.step_label ? `: ${i.step_label}` : ''}
                  </span>
                </div>
              )}
              {i.status === 'failed' && i.message ? <span className="block text-gray-400">{i.message}</span> : null}
            </li>
          ))}
        </ul>
      )}

      {asking && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Run a BEC search?" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Run a BEC search?</h3>
            <p className="mt-2 text-sm text-gray-300">CIPP will investigate {email}: audit log, sign-ins, inbox rules, forwarding, app consents, mail flow and attacker addresses. It changes nothing in the tenant.</p>
            {problem && <p className="mt-2 text-sm text-red-300">{problem}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setAsking(false)} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              <button type="button" onClick={() => void start()} disabled={busy} className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
                {busy ? 'Starting…' : 'Yes, run it'}
              </button>
            </div>
          </div>
        </div>
      )}
      {viewing && <ReportWindow clientId={clientId} item={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}
