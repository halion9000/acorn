/**
 * Small pure helpers for the client review page: which answers A.C.O.R.N worked out by itself, how many questions are still open in each section, the CSV of the whole review, and the sections a person
 * has folded away (kept in the browser). None of this calls the API.
 */
import type { Review } from "./ClientReview";

/** A status that means "nobody has answered this": A.C.O.R.N could not, and no person has. */
export const OPEN_STATUSES = new Set(["unknown", "needs_person"]);

/** True when A.C.O.R.N worked the answer out from its own data: there is an answer, and no person typed over it. A "not applicable" a person chose is theirs. */
export function answeredAutomatically(status: string, manual: boolean | undefined): boolean {
  return !manual && !OPEN_STATUSES.has(status) && status !== "not_applicable";
}

export interface SectionCounts {
  readiness: number;
  tech: number;
  m365: number;
  assess: number;
}

/** How many questions are still open (unanswered by A.C.O.R.N and by a person) in each section of the review. */
export function openCounts(review: Review): SectionCounts {
  const open = (items: { status: string }[] | undefined): number => (items ?? []).filter((i) => OPEN_STATUSES.has(i.status)).length;
  return { readiness: open(review.readiness.items), tech: open(review.tech_stack), m365: open(review.m365), assess: open(review.assess) };
}

/** "5 open" or "all answered", for a section heading; nothing when the section has no questions. */
export function openLabel(open: number, total: number): string {
  if (total === 0) return "";
  return open === 0 ? "all answered" : `${open} of ${total} open`;
}

const CSV_HEADER = ["Section", "Group", "Question", "Status", "Answered by", "Evidence", "Note", "Licence"];

/** One CSV cell. A cell that a spreadsheet would run as a formula (it starts with = + - @ or a control character) gets a leading apostrophe; quotes, commas and line breaks are quoted. */
export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function answeredBy(status: string, manual: boolean | undefined): string {
  if (OPEN_STATUSES.has(status)) return "not answered";
  return answeredAutomatically(status, manual) ? "automatic" : "typed by a person";
}

/** The whole review as CSV, one row per question, for a spreadsheet or a client file. */
export function reviewCsv(review: Review): string {
  const rows: unknown[][] = [];
  for (const i of review.readiness.items) rows.push(["Cyber-insurance readiness", "", i.question, i.status, answeredBy(i.status, i.manual), i.evidence, i.note ?? "", ""]);
  for (const a of review.tech_stack ?? []) {
    rows.push(["Technology stack", a.group, a.question, a.status === "unknown" ? "ask the client" : (a.suggested ?? a.status), answeredBy(a.status, a.manual), a.evidence, a.note ?? "", ""]);
  }
  for (const a of review.m365 ?? []) rows.push(["Microsoft 365", a.group, a.question, a.status, answeredBy(a.status, a.manual), a.evidence, a.note ?? "", a.license ?? ""]);
  for (const a of review.assess ?? []) rows.push(["Infrastructure and security assessment", `${a.sheet} / ${a.group}`, a.question, a.status, answeredBy(a.status, a.manual), a.evidence, a.note ?? "", ""]);
  return [CSV_HEADER, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/** A file name for the CSV: the client's name made safe, and the day. */
export function csvFileName(review: Review): string {
  const name = (review.client_name ?? "client").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "client";
  return `client-review-${name}-${review.generated_at.slice(0, 10)}.csv`;
}

const STORE_KEY = "client-review-folded";

/** The sections a person folded away last time. Browser storage can be blocked or hold rubbish: then nothing is folded. */
export function loadFolded(): string[] {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string").slice(0, 20) : [];
  } catch {
    return [];
  }
}

export function saveFolded(folded: string[]): void {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(folded.slice(0, 20)));
  } catch {
    // a fold that cannot be remembered only means the section opens again next time
  }
}
