/**
 * Client Risk Score (first called vCIO Risk Scoring; the routes keep that name): the types and the calls behind the page, plus the small pure parts the page shows (percentages, which questions a filter keeps, the CSV).
 * The scoring itself is done by the API (its vcio-risk-scoring routes); nothing here re-computes a score.
 */
import { apiRequest } from '@/lib/api';
import { csvText } from '@/lib/csv';

export type RiskSeverity = 'Critical' | 'High' | 'Medium' | 'Low';
export type RiskRating = 'green' | 'amber' | 'red' | 'na';
export type RiskPlatform = 'm365' | 'google' | 'both';

export interface RiskQuestion {
  id: string;
  category: string;
  subsection: string;
  text: string;
  type: 'yesno' | 'vendor';
  preferred: string;
  good: 'Yes' | 'No';
  severity: RiskSeverity;
  csf: string;
  csf_function: string;
  csf_name: string;
}

export interface RiskSettings {
  points: Record<RiskSeverity, number>;
  partial: number;
  unknown: number;
  alternative: number;
  cap_on: boolean;
  cap: number;
  green: number;
  amber: number;
  weights: Record<string, number>;
}

export interface RiskLibrary {
  questions: RiskQuestion[];
  categories: string[];
  csf_functions: string[];
  severities: RiskSeverity[];
  yesno_answers: string[];
  vendor_answers: string[];
  defaults: RiskSettings;
}

export interface RiskAggregate {
  name: string;
  questions: number;
  answered: number;
  points_possible: number;
  points_earned: number;
  critical_gaps: number;
  raw: number | null;
  score: number | null;
  rating: RiskRating;
}

export interface RiskCategory extends RiskAggregate {
  weight: number;
  excluded: boolean;
  sections: RiskAggregate[];
}

export interface RiskGap {
  id: string;
  severity: RiskSeverity;
  answer: string;
  points_lost: number;
}

export interface RiskScorecard {
  overall: number | null;
  rating: RiskRating;
  categories: RiskCategory[];
  csf: RiskAggregate[];
  gaps: RiskGap[];
  gap_count: number;
  total: number;
  answered: number;
  open: number;
  unknown: number;
  alternative_vendors: number;
  settings: RiskSettings;
}

export interface RiskAnswer {
  answer?: string | null;
  vendor?: string | null;
  note?: string | null;
  /** 'auto' when the integrations filled the answer in (through the client's Client Review) and nobody has changed it. */
  source?: string | null;
  /** What the integrations saw, for an answer they filled in. */
  evidence?: string | null;
}

export interface RiskAutofill {
  assessment: RiskAssessment;
  filled: number;
  changed: number;
  kept_by_hand: number;
  cleared: number;
  answered_by_integrations: number;
  /** How many questions of this assessment are also a Client Review question: the most the integrations could ever answer here. */
  shared_with_review?: number;
  /** Whether anything was written (nothing is, when no answer moved). */
  saved?: boolean;
}

export interface RiskAssessor {
  name: string;
  email: string | null;
}

export type RiskDirection = 'up' | 'down' | 'flat' | 'none';

export interface RiskTrendPoint {
  id: string;
  review_date: string;
  score: number | null;
  rating: RiskRating;
  answered: number;
  assessor: string;
  /** Percentage points since the last assessment that had a score; null for the first one and for one with nothing answered. */
  change: number | null;
  direction: RiskDirection;
  compared_with: string | null;
  categories: Record<string, number | null>;
}

export interface RiskCategoryChange {
  name: string;
  before: number;
  after: number;
  change: number;
  direction: RiskDirection;
}

export interface RiskClientTrend {
  client_id: string;
  client_name: string | null;
  points: RiskTrendPoint[];
  categories: RiskCategoryChange[];
}

export interface RiskClientTrendRow {
  client_id: string;
  client_name: string | null;
  assessments: number;
  latest_date: string;
  latest_score: number | null;
  rating: RiskRating;
  previous_date: string | null;
  previous_score: number | null;
  change: number | null;
  direction: RiskDirection;
}

export interface RiskSettingsAnswer {
  settings: RiskSettings;
  defaults: RiskSettings;
  using_defaults: boolean;
  rescored: number;
}

export interface RiskAssessmentSummary {
  id: string;
  client_id: string;
  client_name: string | null;
  review_date: string;
  platform: RiskPlatform;
  assessor: string;
  score: number | null;
  rating: RiskRating;
  answered: number;
  updated_at: string;
  updated_by: string | null;
}

export interface RiskAssessment extends RiskAssessmentSummary {
  answers: Record<string, RiskAnswer>;
  severity: Record<string, RiskSeverity>;
  scorecard: RiskScorecard;
}

const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const vcioRiskApi = {
  library: () => apiRequest<RiskLibrary>('/api/v1/vcio-risk-scoring/library'),
  list: (clientId?: string) => apiRequest<{ items: RiskAssessmentSummary[] }>('/api/v1/vcio-risk-scoring/assessments', { params: clientId ? { client_id: clientId } : undefined }),
  create: (body: { client_id?: string; review_date?: string; platform: RiskPlatform; assessor: string }) => apiRequest<RiskAssessment>('/api/v1/vcio-risk-scoring/assessments', json('POST', body)),
  get: (id: string) => apiRequest<RiskAssessment>(`/api/v1/vcio-risk-scoring/assessments/${encodeURIComponent(id)}`),
  update: (id: string, body: { review_date?: string; platform?: RiskPlatform; assessor?: string; severity?: Record<string, RiskSeverity | null> }) =>
    apiRequest<RiskAssessment>(`/api/v1/vcio-risk-scoring/assessments/${encodeURIComponent(id)}`, json('PATCH', body)),
  answer: (id: string, items: { id: string; answer?: string | null; vendor?: string | null; note?: string | null }[]) =>
    apiRequest<RiskAssessment>(`/api/v1/vcio-risk-scoring/assessments/${encodeURIComponent(id)}/answers`, json('PUT', { items })),
  /** The organisation's A.C.O.R.N users, for the assessor of an assessment. */
  assessors: () => apiRequest<{ items: RiskAssessor[] }>('/api/v1/vcio-risk-scoring/assessors'),
  /** The clients an assessment can be started for. Readable with alert access, unlike the MSSP client list (which a vCIO role does not hold). */
  clients: () => apiRequest<{ items: { id: string; name: string }[] }>('/api/v1/vcio-risk-scoring/clients'),
  /** Every client's latest score and how it moved since the assessment before, biggest drop first. */
  trends: () => apiRequest<{ clients: RiskClientTrendRow[] }>('/api/v1/vcio-risk-scoring/trends'),
  /** One client's score over time, with the change per category between its last two scored assessments. */
  clientTrend: (clientId: string) => apiRequest<RiskClientTrend>(`/api/v1/vcio-risk-scoring/trends/${encodeURIComponent(clientId)}`),
  /** Fill in what the integrations can answer, from the client's Client Review. An answer set by hand is never replaced. */
  autofill: (id: string) => apiRequest<RiskAutofill>(`/api/v1/vcio-risk-scoring/assessments/${encodeURIComponent(id)}/autofill`, { method: 'POST' }),
  /** The organisation's scoring settings (kept under Settings). */
  settings: () => apiRequest<RiskSettingsAnswer>('/api/v1/vcio-risk-scoring/settings'),
  saveSettings: (settings: RiskSettings | Record<string, never>) => apiRequest<RiskSettingsAnswer>('/api/v1/vcio-risk-scoring/settings', json('PUT', { settings })),
  remove: (id: string) => apiRequest<{ deleted: boolean }>(`/api/v1/vcio-risk-scoring/assessments/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

/** A score as a whole percentage, or a dash when nothing was answered. */
export const pct = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);

export const RATING_TEXT: Record<RiskRating, string> = { green: 'Green', amber: 'Amber', red: 'Red', na: 'Not assessed' };

/** A change in points as people read it: "▲ 8 points", "▼ 3.5 points", "no change"; empty when there is nothing to compare with. */
export function changeText(change: number | null | undefined, direction: RiskDirection): string {
  if (change === null || change === undefined || direction === 'none') return '';
  if (direction === 'flat') return 'no change';
  const size = Math.abs(change);
  return `${direction === 'up' ? '▲' : '▼'} ${size} point${size === 1 ? '' : 's'}`;
}

export const DIRECTION_CLASS: Record<RiskDirection, string> = { up: 'text-emerald-300', down: 'text-red-300', flat: 'text-gray-400', none: 'text-gray-500' };

/** The assessor choices: the organisation's users, plus the name an assessment already carries when that person is no longer one of them (so opening an old assessment does not blank it). */
export function assessorChoices(users: RiskAssessor[], current: string): string[] {
  const names = users.map((u) => u.name);
  return current && !names.some((n) => n.toLowerCase() === current.toLowerCase()) ? [...names, current] : names;
}

/** What a fill-in from the integrations did, in one sentence. */
export function autofillSentence(r: Pick<RiskAutofill, 'filled' | 'changed' | 'kept_by_hand' | 'cleared' | 'answered_by_integrations' | 'shared_with_review'>): string {
  const shared = r.shared_with_review ? ` ${r.shared_with_review} of the questions here are also Client Review questions; it answers ${r.answered_by_integrations} of them for this client, and the rest need a person.` : '';
  if (r.answered_by_integrations === 0) return `The integrations have no answer for this client yet: nothing was filled in.${shared}`;
  const parts = [`${r.filled} answer${r.filled === 1 ? '' : 's'} filled in from the integrations`];
  if (r.changed) parts.push(`${r.changed} updated`);
  if (r.kept_by_hand) parts.push(`${r.kept_by_hand} you set by hand left as ${r.kept_by_hand === 1 ? 'it is' : 'they are'}`);
  if (r.cleared) parts.push(`${r.cleared} taken out because the integrations no longer say`);
  return `${parts.join(', ')}.${shared}`;
}

/** Whether a fill changed anything a person should be told about. */
export const autofillMoved = (r: Pick<RiskAutofill, 'filled' | 'changed' | 'cleared'>): boolean => r.filled + r.changed + r.cleared > 0;

/** Whether the client's platform makes a question moot (the other suite's questions). */
export const excludedFor = (q: Pick<RiskQuestion, 'category'>, platform: RiskPlatform): boolean =>
  (platform === 'm365' && q.category === 'Google Workspace') || (platform === 'google' && q.category === 'Microsoft 365');

/** The answer that earns the points: "Preferred" for a vendor question, otherwise the question's good answer. */
export const goodAnswer = (q: Pick<RiskQuestion, 'type' | 'good'>): string => (q.type === 'vendor' ? 'Preferred' : q.good);

/** Whether an answer loses points: answered, not N/A, and not the full-credit answer (an alternative vendor keeps its points by default). */
export function losesPoints(q: Pick<RiskQuestion, 'type' | 'good'>, answer: string | null | undefined): boolean {
  if (!answer || answer === 'N/A') return false;
  if (q.type === 'vendor') return answer === 'None' || answer === 'Unknown';
  return answer !== q.good;
}

export type QuestionFilter = 'all' | 'open' | 'gaps' | 'unknown' | 'critical' | 'auto';

/** The questions a filter, a category and a search keep, in the library's order; the other platform's questions are never shown. */
export function keepQuestions(
  questions: RiskQuestion[],
  a: Pick<RiskAssessment, 'answers' | 'severity' | 'platform'>,
  opts: { filter: QuestionFilter; category: string; search: string },
): RiskQuestion[] {
  const needle = opts.search.trim().toLowerCase();
  return questions.filter((q) => {
    if (excludedFor(q, a.platform)) return false;
    if (opts.category && q.category !== opts.category) return false;
    const answer = a.answers[q.id]?.answer ?? null;
    if (opts.filter === 'open' && answer) return false;
    if (opts.filter === 'gaps' && !losesPoints(q, answer)) return false;
    if (opts.filter === 'unknown' && answer !== 'Unknown') return false;
    if (opts.filter === 'critical' && (a.severity[q.id] ?? q.severity) !== 'Critical') return false;
    if (opts.filter === 'auto' && a.answers[q.id]?.source !== 'auto') return false;
    return !needle || q.text.toLowerCase().includes(needle) || q.id.toLowerCase().includes(needle) || q.subsection.toLowerCase().includes(needle);
  });
}

/** The whole assessment as a CSV: one row per question the client is asked, with its answer, the vendor in use and the note. */
export function assessmentCsv(questions: RiskQuestion[], a: Pick<RiskAssessment, 'answers' | 'severity' | 'platform'>): string {
  return csvText(
    ['ID', 'Category', 'Section', 'Question', 'Severity', 'Good answer', 'Answer', 'Vendor / product in use', 'Evidence / notes', 'NIST CSF 2.0', 'CSF function', 'Answer source', 'What the integrations saw'],
    questions
      .filter((q) => !excludedFor(q, a.platform))
      .map((q) => [q.id, q.category, q.subsection, q.text, a.severity[q.id] ?? q.severity, goodAnswer(q), a.answers[q.id]?.answer ?? '', a.answers[q.id]?.vendor ?? '', a.answers[q.id]?.note ?? '', q.csf, q.csf_function, a.answers[q.id]?.source === 'auto' ? 'Integrations' : a.answers[q.id]?.answer ? 'Typed' : '', a.answers[q.id]?.evidence ?? '']),
  );
}
