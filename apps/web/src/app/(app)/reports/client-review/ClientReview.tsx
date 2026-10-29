"use client";

/**
 * Client review: one client's tool coverage, Multi-Factor, Microsoft Secure Score, the last 30 days of alerts and cases, and a cyber-insurance readiness checklist, on one printable page.
 * Backed by GET /api/v1/client-review/{client}. Every answer is evidence from the connected tools; what A.C.O.R.N does not hold is shown as "Not known", never guessed.
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { authFetch } from "@/lib/auth-session";
import { VcioSuggestions } from "./VcioSuggestions";
import { AnswerEditor, AnswerMarks } from "./AnswerEditor";
import { answeredAutomatically, csvFileName, loadFolded, openCounts, openLabel, reviewCsv, saveFolded } from "./reviewExport";

export interface Coverage {
  tool: string;
  have: number;
  of: number;
  percent: number | null;
  /** False: the client is not in this tool at all ("Not currently enrolled"). Absent or null: not known. */
  enrolled?: boolean | null;
}

export interface ReadinessItem {
  key: string;
  question: string;
  status: "met" | "partly" | "not_met" | "unknown";
  evidence: string;
  /** A typed status or answer replaces the worked-out one (manual); what A.C.O.R.N had worked out is kept in auto_*. A note changes no answer. */
  manual?: boolean;
  note?: string | null;
  auto_status?: string | null;
}

export interface VcioRecommendation {
  name: string;
  priority: string | null;
  adoption: string;
  due: string | null;
  on_roadmap: boolean;
}

export interface VcioRisk {
  name: string;
  category: string | null;
  priority: string | null;
  impact: number | null;
  likelihood: number | null;
  score: number | null;
  inherent: string | null;
}

export interface TechAnswer {
  key: string;
  group: string;
  question: string;
  /** seen: A.C.O.R.N found something; not_seen: the tool covers other clients but not this one; unknown: A.C.O.R.N cannot see this. */
  status: 'seen' | 'not_seen' | 'unknown';
  suggested: string | null;
  evidence: string;
  /** A typed status or answer replaces the worked-out one (manual); what A.C.O.R.N had worked out is kept in auto_*. A note changes no answer. */
  manual?: boolean;
  note?: string | null;
  auto_status?: string | null;
  auto_suggested?: string | null;
}

export interface M365Answer {
  group: string;
  question: string;
  /** From a check CORE read through CIPP (or the multi-factor list); needs_person when A.C.O.R.N has nothing that answers it. */
  status: 'met' | 'partly' | 'not_met' | 'needs_person';
  evidence: string;
  /** The licence this question's setting needs, when it has one. */
  license?: string | null;
  /** A typed status or answer replaces the worked-out one (manual); what A.C.O.R.N had worked out is kept in auto_*. A note changes no answer. */
  manual?: boolean;
  note?: string | null;
  auto_status?: string | null;
}

/** "20 of 99 answered: 11 met, 1 partly, 8 not met. 79 need a person." */
export function m365Headline(items: M365Answer[]): string {
  const n = (s: M365Answer['status']) => items.filter((i) => i.status === s).length;
  const answered = items.length - n('needs_person');
  return `${answered} of ${items.length} answered: ${n('met')} met, ${n('partly')} partly, ${n('not_met')} not met. ${n('needs_person')} need a person.`;
}

export interface AssessAnswer {
  sheet: string;
  group: string;
  question: string;
  /** From a check A.C.O.R.N runs, where one speaks to the question; needs_person otherwise; not_applicable when a person says it does not apply. */
  status: 'met' | 'partly' | 'not_met' | 'needs_person' | 'not_applicable';
  evidence: string;
  manual?: boolean;
  note?: string | null;
  auto_status?: string | null;
}

const ASSESS_LABEL: Record<string, string> = { needs_person: 'Needs a person', not_applicable: 'Not applicable' };

/** "12 of 145 answered: 7 met, 3 partly, 2 not met. 133 need a person." Not-applicable questions count as answered and are left out of the rest. */
export function assessHeadline(items: AssessAnswer[]): string {
  const n = (s: AssessAnswer['status']) => items.filter((i) => i.status === s).length;
  const answered = items.length - n('needs_person');
  const na = n('not_applicable');
  return `${answered} of ${items.length} answered: ${n('met')} met, ${n('partly')} partly, ${n('not_met')} not met${na ? `, ${na} not applicable` : ''}. ${n('needs_person')} need a person.`;
}

export interface Review {
  client_id: string;
  client_name: string | null;
  generated_at: string;
  window_days: number;
  devices: { endpoints: number; coverage: Coverage[]; stale_agents: number; offline: number; with_known_exploited: number | null; with_ransomware_exploit: number | null };
  mfa: { people: number; with_mfa: number; not_required: number; without_mfa: number; admins_without_mfa: number } | null;
  secure_score: { percent: number; current: number; max: number; average: number | null; taken_at: string } | null;
  alerts: { open: number; critical_open: number; high_open: number; opened_30d: number; closed_30d: number };
  cases: { open: number; opened_30d: number; resolved_30d: number };
  readiness: { met: number; partly: number; not_met: number; unknown: number; items: ReadinessItem[] };
  tech_stack?: TechAnswer[];
  m365?: M365Answer[];
  m365_refreshed_at?: string | null;
  assess?: AssessAnswer[];
  vcio?: { recommendations: { total: number; pending: number; adopted: number; declined: number; top: VcioRecommendation[] }; risks: VcioRisk[]; refreshed_at: string } | null;
}

interface ClientChoice {
  id: string;
  name: string;
}

export const TOOL_NAMES: Record<string, string> = {
  huntress: "Huntress (endpoint detection)",
  ninjaone: "NinjaOne (management)",
  dnsfilter: "DNSFilter (web filtering)",
  threatmate: "ThreatMate (vulnerability scanning)",
  fieldeffect: "Field Effect (monitoring)",
  autoelevate: "AutoElevate (privilege control)",
  screenconnect: "ScreenConnect (remote support)",
  addigy: "Addigy (Mac management)",
};

const STATUS: Record<ReadinessItem["status"], { label: string; className: string }> = {
  met: { label: "Met", className: "bg-emerald-500/20 text-emerald-300" },
  partly: { label: "Partly", className: "bg-amber-500/20 text-amber-300" },
  not_met: { label: "Not met", className: "bg-red-500/20 text-red-300" },
  unknown: { label: "Not known", className: "bg-slate-600/30 text-slate-300" },
};

/** One plain sentence for the top of the review: how many answers are met, and what needs a person. */
export function readinessHeadline(r: Review["readiness"]): string {
  const total = r.items.length;
  const gaps = r.not_met + r.partly;
  const parts = [`${r.met} of ${total} answers are met`];
  if (gaps > 0) parts.push(`${gaps} ${gaps === 1 ? "needs" : "need"} work`);
  if (r.unknown > 0) parts.push(`${r.unknown} ${r.unknown === 1 ? "is" : "are"} not known to A.C.O.R.N`);
  return `${parts.join(", ")}.`;
}

/** "Due 12 Jun 2026" or an empty string, from the ISO date vCIO Toolbox's summary carries. */
export function dueText(iso: string | null): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
  if (!m) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[Number(m[2]) - 1];
  return month ? `due ${Number(m[3])} ${month} ${m[1]}` : "";
}

/** Tools worth showing: the ones some of this client's machines should be running, in the order given by the API. */
export function visibleCoverage(coverage: Coverage[]): Coverage[] {
  return coverage.filter((c) => c.of > 0);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(res.status === 404 ? "That client was not found." : `The API answered ${res.status}`);
  return (await res.json()) as T;
}

/** A tag for a row A.C.O.R.N answered from its own data, so a person can tell which answers they still have to check or give. */
function AutoTag({ status, manual }: { status: string; manual: boolean | undefined }) {
  return answeredAutomatically(status, manual) ? (
    <span data-testid="auto-answered" className="mt-0.5 block text-[10px] uppercase tracking-wide text-slate-500">
      automatic
    </span>
  ) : null;
}

function Card({
  title,
  children,
  section,
  summary,
  folded,
  onToggle,
}: {
  title: string;
  children: React.ReactNode;
  /** A section a person can fold away (the long question lists); the choice is remembered. */
  section?: string;
  /** Next to the title, for example how many questions are open. */
  summary?: string;
  folded?: string[];
  onToggle?: (section: string) => void;
}) {
  const isFolded = !!section && !!folded?.includes(section);
  return (
    <section className="rounded-lg border border-slate-800 p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          {title}
          {summary ? (
            <span data-testid={`open-${section}`} className="ml-2 text-xs font-normal normal-case tracking-normal text-slate-500">
              {summary}
            </span>
          ) : null}
        </h2>
        {section && onToggle ? (
          <button
            type="button"
            aria-expanded={!isFolded}
            aria-label={`${isFolded ? "Show" : "Hide"} ${title}`}
            onClick={() => onToggle(section)}
            className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-800 print:hidden"
          >
            {isFolded ? "Show" : "Hide"}
          </button>
        ) : null}
      </div>
      <div className={isFolded ? "hidden print:block" : undefined}>{children}</div>
    </section>
  );
}

export function ClientReview() {
  const params = useSearchParams();
  const [clients, setClients] = useState<ClientChoice[] | null>(null);
  const [clientId, setClientId] = useState(params?.get("client") ?? "");
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after an answer is typed, so the review is read again with it.
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);
  // The sections a person folded away last time (read after the first paint: browser storage does not exist on the server).
  const [folded, setFolded] = useState<string[]>([]);
  useEffect(() => setFolded(loadFolded()), []);
  const toggle = (section: string) =>
    setFolded((prev) => {
      const next = prev.includes(section) ? prev.filter((x) => x !== section) : [...prev, section];
      saveFolded(next);
      return next;
    });
  const downloadCsv = () => {
    if (!review) return;
    const url = URL.createObjectURL(new Blob([reviewCsv(review)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = csvFileName(review);
    link.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    let live = true;
    getJson<{ id: string; name: string }[]>("/api/v1/mssp/children")
      .then((list) => {
        if (live) setClients(list.map((c) => ({ id: c.id, name: c.name })).sort((a, b) => a.name.localeCompare(b.name)));
      })
      .catch(() => {
        if (live) setClients([]);
      });
    return () => {
      live = false;
    };
  }, []);

  // Another client starts from a blank page; reading the same client again (after an answer is typed) keeps what is shown until the new copy arrives.
  useEffect(() => {
    setReview(null);
  }, [clientId]);

  useEffect(() => {
    if (!clientId) {
      setReview(null);
      return;
    }
    let live = true;
    setError(null);
    getJson<Review>(`/api/v1/client-review/${encodeURIComponent(clientId)}`)
      .then((r) => {
        if (live) setReview(r);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Could not load the review");
      });
    return () => {
      live = false;
    };
  }, [clientId, version]);

  const coverage = useMemo(() => (review ? visibleCoverage(review.devices.coverage) : []), [review]);
  const open = useMemo(() => (review ? openCounts(review) : null), [review]);

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Client review</h1>
          <p className="mt-1 text-sm text-slate-400">
            Coverage, identity, alerts and a cyber-insurance readiness checklist for one client, from the tools A.C.O.R.N is connected to. Evidence, not a certification: what A.C.O.R.N cannot see is marked Not known.
          </p>
        </div>
        <div className="flex items-center gap-2 print:hidden">
          <select
            aria-label="Client"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200"
          >
            <option value="">Choose a client...</option>
            {(clients ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button type="button" disabled={!review} onClick={downloadCsv} className="rounded border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40">
            Download CSV
          </button>
          <button type="button" disabled={!review} onClick={() => window.print()} className="rounded border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40">
            Print or save as PDF
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
      {!clientId && !error && <p className="text-sm text-slate-500">Choose a client to see its review.</p>}
      {clientId && !review && !error && <p className="text-sm text-slate-500">Loading...</p>}

      {review && (
        <>
          <div>
            <h2 className="text-lg font-semibold text-slate-100" data-testid="review-title">
              {review.client_name ?? "This organization"}
            </h2>
            <p className="text-sm text-slate-300" data-testid="review-headline">
              {readinessHeadline(review.readiness)}
            </p>
            {open && (
              <p className="text-xs text-slate-400" data-testid="open-summary">
                Questions still open: {open.readiness} in readiness, {open.tech} in technology, {open.m365} in Microsoft 365, {open.assess} in the assessment.
              </p>
            )}
            <p className="text-xs text-slate-500">Read {new Date(review.generated_at).toLocaleString()}. Alerts and cases cover the last {review.window_days} days.</p>
          </div>

          <Card title="Cyber-insurance readiness" section="readiness" summary={open ? openLabel(open.readiness, review.readiness.items.length) : undefined} folded={folded} onToggle={toggle}>
            <ul className="space-y-2" data-testid="readiness">
              {review.readiness.items.map((i) => (
                <li key={i.key} className="flex items-start gap-3 text-sm">
                  <span className="mt-0.5 w-20 shrink-0 text-center">
                    <span className={`block rounded px-2 py-0.5 text-[11px] font-medium ${STATUS[i.status].className}`}>{STATUS[i.status].label}</span>
                    <AutoTag status={i.status} manual={i.manual} />
                  </span>
                  <span className="flex-1">
                    <span className="text-slate-200">{i.question}</span>
                    <span className="block text-xs text-slate-500">{i.evidence}</span>
                    <AnswerMarks manual={i.manual} note={i.note} suggested={i.auto_status ? STATUS[i.auto_status as ReadinessItem["status"]]?.label : null} />
                    <AnswerEditor clientId={review.client_id} section="readiness" questionKey={i.key} status={i.status} note={i.note} manual={i.manual} onSaved={reload} />
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          {(review.tech_stack ?? []).length > 0 && (
            <Card title="Technology stack: suggested answers" section="tech" summary={open ? openLabel(open.tech, (review.tech_stack ?? []).length) : undefined} folded={folded} onToggle={toggle}>
              <p className="mb-2 text-xs text-slate-500">
                The vCIO Toolbox review template&apos;s technology questions, with what A.C.O.R.N can see. Anything marked Ask the client is something A.C.O.R.N has no way to see. Nothing here is sent to vCIO Toolbox.
              </p>
              <table className="w-full text-left text-sm" data-testid="tech-stack">
                <tbody>
                  {(review.tech_stack ?? []).map((a, i, all) => (
                    <Fragment key={a.key}>
                      {(i === 0 || all[i - 1].group !== a.group) && (
                        <tr>
                          <th colSpan={3} className="pt-3 text-xs font-medium uppercase text-slate-500">
                            {a.group}
                          </th>
                        </tr>
                      )}
                      <tr className="border-b border-slate-800 align-top">
                        <td className="py-1.5 pr-3 text-slate-300">{a.question}</td>
                        <td className={`w-32 pr-3 ${a.status === 'seen' ? 'text-emerald-300' : a.status === 'not_seen' ? 'text-amber-300' : 'text-slate-500'}`}>
                          {a.status === 'unknown' ? 'Ask the client' : a.suggested}
                          {a.status !== 'unknown' && <AutoTag status="seen" manual={a.manual} />}
                        </td>
                        <td className="text-xs text-slate-500">
                          {a.evidence}
                          <AnswerMarks manual={a.manual} note={a.note} suggested={a.manual ? (a.auto_status === 'unknown' ? 'Ask the client' : a.auto_suggested) : null} />
                          <AnswerEditor clientId={review.client_id} section="tech" questionKey={a.key} status={a.status} answer={a.suggested} note={a.note} manual={a.manual} onSaved={reload} />
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {(review.m365 ?? []).length > 0 && (
            <Card title="Microsoft 365: suggested answers" section="m365" summary={open ? openLabel(open.m365, (review.m365 ?? []).length) : undefined} folded={folded} onToggle={toggle}>
              <p className="mb-1 text-sm text-slate-300" data-testid="m365-headline">
                {m365Headline(review.m365 ?? [])}
              </p>
              <p className="mb-2 text-xs text-slate-500">
                The vCIO Toolbox review template&apos;s Microsoft 365 questions. An answer is shown only where A.C.O.R.N read the setting through CIPP
                {review.m365_refreshed_at ? ` (last read ${new Date(review.m365_refreshed_at).toLocaleDateString()})` : ''} or holds the multi-factor list; the rest need a person. Nothing here is sent to vCIO Toolbox.
              </p>
              <table className="w-full text-left text-sm" data-testid="m365">
                <tbody>
                  {(review.m365 ?? []).map((a, i, all) => (
                    <Fragment key={a.question}>
                      {(i === 0 || all[i - 1].group !== a.group) && (
                        <tr>
                          <th colSpan={3} className="pt-3 text-xs font-medium uppercase text-slate-500">
                            {a.group}
                          </th>
                        </tr>
                      )}
                      <tr className="border-b border-slate-800 align-top">
                        <td className="py-1.5 pr-3 text-slate-300">{a.question}</td>
                        <td className="w-24 pr-3">
                          {a.status === 'needs_person' ? (
                            <span className="text-slate-500">Needs a person</span>
                          ) : (
                            <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${STATUS[a.status].className}`}>{STATUS[a.status].label}</span>
                          )}
                          <AutoTag status={a.status} manual={a.manual} />
                        </td>
                        <td className="text-xs text-slate-500">
                          {a.evidence}
                          {a.license && (
                            <span data-testid="licence-note" className="block text-amber-300/80">
                              {a.license}
                            </span>
                          )}
                          <AnswerMarks manual={a.manual} note={a.note} suggested={a.auto_status ? (a.auto_status === 'needs_person' ? 'Needs a person' : STATUS[a.auto_status as ReadinessItem['status']]?.label) : null} />
                          <AnswerEditor clientId={review.client_id} section="m365" questionKey={a.question} status={a.status} note={a.note} manual={a.manual} onSaved={reload} />
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {(review.assess ?? []).length > 0 && (
            <Card title="Infrastructure and security assessment" section="assess" summary={open ? openLabel(open.assess, (review.assess ?? []).length) : undefined} folded={folded} onToggle={toggle}>
              <p className="mb-1 text-sm text-slate-300" data-testid="assess-headline">
                {assessHeadline(review.assess ?? [])}
              </p>
              <p className="mb-2 text-xs text-slate-500">
                The vCIO Toolbox assessment template&apos;s network, server, workstation, security, backup and Google Workspace questions. An answer is suggested only where a check A.C.O.R.N already runs speaks to the question
                (the evidence names it); the rest need a person, who can answer each one here or mark it not applicable. Nothing here is sent to vCIO Toolbox.
              </p>
              <table className="w-full text-left text-sm" data-testid="assess">
                <tbody>
                  {(review.assess ?? []).map((a, i, all) => (
                    <Fragment key={a.question}>
                      {(i === 0 || all[i - 1].sheet !== a.sheet || all[i - 1].group !== a.group) && (
                        <tr>
                          <th colSpan={3} className="pt-3 text-xs font-medium uppercase text-slate-500">
                            {a.sheet} · {a.group}
                          </th>
                        </tr>
                      )}
                      <tr className="border-b border-slate-800 align-top">
                        <td className="py-1.5 pr-3 text-slate-300">{a.question}</td>
                        <td className="w-28 pr-3">
                          {a.status === 'needs_person' || a.status === 'not_applicable' ? (
                            <span className="text-slate-500">{ASSESS_LABEL[a.status]}</span>
                          ) : (
                            <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${STATUS[a.status].className}`}>{STATUS[a.status].label}</span>
                          )}
                          <AutoTag status={a.status} manual={a.manual} />
                        </td>
                        <td className="text-xs text-slate-500">
                          {a.evidence}
                          <AnswerMarks manual={a.manual} note={a.note} suggested={a.auto_status ? (ASSESS_LABEL[a.auto_status] ?? STATUS[a.auto_status as ReadinessItem['status']]?.label) : null} />
                          <AnswerEditor clientId={review.client_id} section="assess" questionKey={a.question} status={a.status} note={a.note} manual={a.manual} onSaved={reload} />
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <Card title="Tool coverage">
              {coverage.length === 0 ? (
                <p className="text-sm text-slate-500">No computers are listed for this client.</p>
              ) : (
                <ul className="space-y-2 text-sm" data-testid="coverage">
                  {coverage.map((c) => (
                    <li key={c.tool} data-testid={c.enrolled === false ? "not-enrolled" : undefined}>
                      {c.enrolled === false ? (
                        <div className="flex justify-between text-slate-500">
                          <span>{TOOL_NAMES[c.tool] ?? c.tool}</span>
                          <span>Not currently enrolled</span>
                        </div>
                      ) : (
                      <>
                      <div className="flex justify-between text-slate-300">
                        <span>{TOOL_NAMES[c.tool] ?? c.tool}</span>
                        <span>
                          {c.have} of {c.of}
                          {c.percent !== null ? ` (${Math.round(c.percent)}%)` : ""}
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 rounded bg-slate-800" aria-hidden="true">
                        <div className={`h-1.5 rounded ${(c.percent ?? 0) >= 90 ? "bg-emerald-500" : (c.percent ?? 0) >= 60 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${Math.min(100, c.percent ?? 0)}%` }} />
                      </div>
                      </>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-3 text-xs text-slate-500">
                {review.devices.endpoints} computers. {review.devices.stale_agents} with an agent that has not checked in for two weeks, {review.devices.offline} offline for a week or more.
                {review.devices.with_known_exploited !== null ? ` ${review.devices.with_known_exploited} with a known-exploited vulnerability.` : ""}
              </p>
            </Card>

            <Card title="Identity">
              {review.mfa ? (
                <p className="text-sm text-slate-300" data-testid="mfa-line">
                  {review.mfa.with_mfa} of {review.mfa.people} people have a required second factor; {review.mfa.without_mfa} have none, {review.mfa.admins_without_mfa} of them administrators.
                </p>
              ) : (
                <p className="text-sm text-slate-500">No multi-factor data for this client yet.</p>
              )}
              {review.secure_score ? (
                <p className="mt-2 text-sm text-slate-300" data-testid="score-line">
                  Microsoft Secure Score {review.secure_score.percent}% ({review.secure_score.current} of {review.secure_score.max})
                  {review.secure_score.average !== null ? `, Microsoft's average is ${review.secure_score.average}` : ""}.
                </p>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No Microsoft Secure Score read for this client yet.</p>
              )}
            </Card>

            {review.vcio ? (
              <Card title="From vCIO Toolbox">
                <p className="text-sm text-slate-300" data-testid="vcio-line">
                  {review.vcio.recommendations.total} recommendations: {review.vcio.recommendations.pending} pending, {review.vcio.recommendations.adopted} adopted, {review.vcio.recommendations.declined} declined.
                </p>
                {review.vcio.recommendations.top.length > 0 && (
                  <ul className="mt-2 space-y-1 text-sm" data-testid="vcio-top">
                    {review.vcio.recommendations.top.map((r) => (
                      <li key={r.name} className="text-slate-300">
                        {r.name}
                        <span className="text-xs text-slate-500">
                          {r.priority ? ` · ${r.priority}` : ""}
                          {dueText(r.due) ? ` · ${dueText(r.due)}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {review.vcio.risks.length > 0 && (
                  <>
                    <p className="mb-1 mt-3 text-xs uppercase text-slate-500">Risks</p>
                    <ul className="space-y-1 text-sm" data-testid="vcio-risks">
                      {review.vcio.risks.map((k) => (
                        <li key={k.name} className="text-slate-300">
                          {k.name}
                          <span className="text-xs text-slate-500">
                            {k.score !== null ? ` · score ${k.score}` : ""}
                            {k.impact !== null && k.likelihood !== null ? ` (impact ${k.impact}, likelihood ${k.likelihood})` : ""}
                            {k.category ? ` · ${k.category}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <p className="mt-2 text-xs text-slate-500">Read from vCIO Toolbox on {new Date(review.vcio.refreshed_at).toLocaleDateString()}. The IT review answers themselves are not available through its API.</p>
              </Card>
            ) : null}

            <VcioSuggestions clientId={review.client_id} />

            <Card title="Alerts">
              <p className="text-sm text-slate-300" data-testid="alerts-line">
                {review.alerts.open} open ({review.alerts.critical_open} critical, {review.alerts.high_open} high). {review.alerts.opened_30d} raised and {review.alerts.closed_30d} closed in the last {review.window_days} days.
              </p>
            </Card>

            <Card title="Cases">
              <p className="text-sm text-slate-300" data-testid="cases-line">
                {review.cases.open} open. {review.cases.opened_30d} opened and {review.cases.resolved_30d} resolved in the last {review.window_days} days.
              </p>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
