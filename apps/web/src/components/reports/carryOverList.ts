/** What a shift hands to the next one: the critical and high alerts still open, and the cases still being worked. */
export interface CarryAlert {
  id: string;
  title: string;
  severity: string;
  clientName?: string;
  assignee?: string;
  createdAt: string;
}

export interface CarryCase {
  id: string;
  caseNumber?: string;
  title: string;
  severity: string;
  status: string;
  clientName?: string;
  assignee?: string;
  createdAt?: string;
}

export interface CarryOverData {
  alerts: CarryAlert[];
  /** How many critical and high alerts are open in all (the list may hold fewer). */
  alertTotal: number;
  cases: CarryCase[];
}

/** How many of each are listed; the rest are counted, not shown. */
export const CARRY_LIST_CAP = 25;

const RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

/** "3 d", "5 h" or "40 min" since the moment; a dash for no date, a bad date or one in the future. */
export function ageLabel(iso: string | undefined, nowMs: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(t) || t > nowMs) return '–';
  const minutes = Math.floor((nowMs - t) / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}

/** Most severe first, then the one that has waited longest. Returns a new list. */
export function byUrgency<T extends { severity: string; createdAt?: string }>(items: T[]): T[] {
  const when = (x: T) => {
    const t = x.createdAt ? Date.parse(x.createdAt) : NaN;
    return Number.isFinite(t) ? t : Number.MAX_SAFE_INTEGER;
  };
  return [...items].sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9) || when(a) - when(b));
}

const who = (assignee: string | undefined) => (assignee ? assignee : 'nobody');
const at = (clientName: string | undefined) => (clientName ? ` (${clientName})` : '');

/** The carry-over list as plain text for a handover message: one line per alert and case, most urgent first, and a count of what the cap left out. */
export function carryOverText(data: CarryOverData, nowMs: number): string {
  const lines: string[] = [`Carry over, ${new Date(nowMs).toISOString().slice(0, 16).replace('T', ' ')} UTC`, ''];
  const alerts = byUrgency(data.alerts).slice(0, CARRY_LIST_CAP);
  lines.push(`Critical and high alerts still open: ${data.alertTotal}`);
  for (const a of alerts) lines.push(`- [${a.severity}] ${a.title || 'Untitled alert'}${at(a.clientName)}, open ${ageLabel(a.createdAt, nowMs)}, with ${who(a.assignee)}`);
  if (data.alertTotal > alerts.length) lines.push(`- and ${data.alertTotal - alerts.length} more`);
  lines.push('');
  const cases = byUrgency(data.cases).slice(0, CARRY_LIST_CAP);
  lines.push(`Cases still open: ${data.cases.length}`);
  for (const c of cases)
    lines.push(`- [${c.severity}] ${c.caseNumber ? `${c.caseNumber} ` : ''}${c.title || 'Untitled case'}${at(c.clientName)}, ${c.status.replace(/_/g, ' ')}, open ${ageLabel(c.createdAt, nowMs)}, with ${who(c.assignee)}`);
  if (data.cases.length > cases.length) lines.push(`- and ${data.cases.length - cases.length} more`);
  return lines.join('\n');
}
