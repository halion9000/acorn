/**
 * The words of a client's weekly update or quarterly review, written from numbers A.C.O.R.N already holds: the score and how it moved, what needs attention, what got worse or better, how the client compares,
 * and (for the quarter) how the tool counts moved. Quantities only: no prices. It is a draft for a person to read and edit; nothing is sent anywhere. Pure: it takes what the page loaded and the date.
 */
export interface SummaryCheck {
  source: string;
  key: string;
  status: string;
  accepted: boolean;
}

export interface SummaryChange {
  source: string;
  key: string;
  status: string;
  previous_status: string | null;
}

export interface SummaryInput {
  name: string;
  days: number;
  now: Date;
  /** Every check the client has now. */
  checks: SummaryCheck[];
  /** The checks of this client that changed in the period. */
  changes: SummaryChange[];
  history: { first: number | null; last: number | null; change: number | null; days_with_data: number } | null;
  compare: { score: number | null; fleet_average: number | null; similar_average: number | null; similar_clients: number } | null;
  counts: { source: string; item: string; count: number; change?: number | null }[] | null;
  devices?: { devices: number; needs_attention: number } | null;
  identity?: { people: number; with_mfa: number; admins_without_mfa: number } | null;
  /** How a check is named in the text, e.g. "NinjaOne: patching". */
  label: (source: string, key: string) => string;
}

const RANK: Record<string, number> = { met: 0, partly: 1, not_met: 2 };
const SHOWN = 5;
const day = (d: Date): string => d.toISOString().slice(0, 10);

function list(items: string[], max: number): string {
  return items.length <= max ? items.join("; ") : `${items.slice(0, max).join("; ")}; and ${items.length - max} more`;
}

export function isWeekly(days: number): boolean {
  return days <= 14;
}

export function buildSummary(i: SummaryInput): string {
  const from = new Date(i.now.getTime() - i.days * 86_400_000);
  const out: string[] = [`${i.name}: ${isWeekly(i.days) ? "weekly update" : "quarterly review"}, ${day(from)} to ${day(i.now)}`, ""];

  const h = i.history;
  if (h && h.last !== null && h.change !== null && h.days_with_data >= 2) {
    const moved = h.change === 0 ? "unchanged" : `${h.change > 0 ? "up" : "down"} ${Math.abs(h.change)} point${Math.abs(h.change) === 1 ? "" : "s"}`;
    out.push(`Score: ${h.last}%, ${moved}${h.first !== null ? ` from ${h.first}%` : ""} over the ${h.days_with_data} days of history we have.`);
  } else if (h && h.last !== null) {
    out.push(`Score today: ${h.last}%. A.C.O.R.N only started keeping the score recently, so there is nothing to compare it with yet.`);
  } else if (i.compare && i.compare.score !== null) {
    out.push(`Score today: ${i.compare.score}%.`);
  } else {
    out.push("No score yet: no tool has sent this client's checks.");
  }
  const c = i.compare;
  if (c && c.fleet_average !== null) out.push(`For comparison: the average across clients is ${c.fleet_average}%${c.similar_average !== null ? `, and ${c.similar_average}% for ${c.similar_clients} clients of about the same size` : ""}.`);

  const open = i.checks.filter((k) => k.status !== "met" && !k.accepted).sort((a, b) => (RANK[b.status] ?? 1) - (RANK[a.status] ?? 1));
  const accepted = i.checks.filter((k) => k.status !== "met" && k.accepted).length;
  out.push(open.length === 0 ? "Nothing needs attention right now." : `${open.length} check${open.length === 1 ? "" : "s"} need${open.length === 1 ? "s" : ""} attention now: ${list(open.map((k) => i.label(k.source, k.key)), SHOWN)}.`);
  if (accepted > 0) out.push(`${accepted} more ${accepted === 1 ? "is an accepted risk" : "are accepted risks"} that someone chose to live with, so ${accepted === 1 ? "it is" : "they are"} not counted against the score.`);

  const worse = i.changes.filter((k) => k.previous_status !== null && (RANK[k.status] ?? 1) > (RANK[k.previous_status] ?? 1));
  const better = i.changes.filter((k) => k.previous_status !== null && (RANK[k.status] ?? 1) < (RANK[k.previous_status] ?? 1));
  if (worse.length > 0) out.push(`Got worse in this period: ${list(worse.map((k) => i.label(k.source, k.key)), SHOWN)}.`);
  if (better.length > 0) out.push(`Got better in this period: ${list(better.map((k) => i.label(k.source, k.key)), SHOWN)}.`);
  if (worse.length === 0 && better.length === 0) out.push("No check changed in this period.");

  if (!isWeekly(i.days)) {
    if (i.devices) out.push(`Devices: ${i.devices.devices}, of which ${i.devices.needs_attention} need attention.`);
    if (i.identity && i.identity.people > 0) out.push(`Multi-Factor: ${i.identity.with_mfa} of ${i.identity.people} people covered; ${i.identity.admins_without_mfa} administrator${i.identity.admins_without_mfa === 1 ? "" : "s"} without it.`);
    const moved = (i.counts ?? []).filter((r) => r.change !== null && r.change !== undefined && r.change !== 0 && r.source !== "halopsa");
    if (moved.length > 0) out.push(`What the tools count, where it moved: ${list(moved.map((r) => `${r.item} (${r.source}) ${r.count - (r.change as number)} to ${r.count}`), 8)}.`);
  }

  out.push("", "Draft for review. The numbers come from A.C.O.R.N; nothing here has been sent to anyone.");
  return out.join("\n");
}
