import type { Case } from '@/lib/api';

const STATUS: Record<string, string> = { open: 'Open', in_progress: 'In progress', pending: 'Pending', resolved: 'Resolved', closed: 'Closed' };

/** "2026-11-10 14:05 UTC": the same on every technician's screen, so a pasted note never depends on who copied it. */
function when(iso: string | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return null;
  return `${t.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

const MAX_EVENTS = 8;
/** How many of the case's alerts a note names; the rest are counted. */
export const MAX_NOTE_ALERTS = 5;

export interface NoteAlert {
  title: string;
  severity: string;
}

/**
 * The first few alerts of a case, read one by one with the page's own call, in the case's order. An alert that cannot be read (deleted, or not this person's to see) is left out, so the note is
 * still made; no ids means no reads.
 */
export async function loadNoteAlerts(ids: readonly string[] | undefined, get: (id: string) => Promise<NoteAlert>): Promise<NoteAlert[]> {
  const settled = await Promise.allSettled((ids ?? []).slice(0, MAX_NOTE_ALERTS).map((id) => get(id)));
  return settled.flatMap((s) => (s.status === 'fulfilled' && s.value ? [{ title: s.value.title, severity: s.value.severity }] : []));
}

/**
 * A case as plain text for a ticket note (HaloPSA or any other): what it is, where it stands, what was done. Plain lines only, no markup, so it pastes cleanly; a field the case does not have
 * is left out rather than shown empty.
 */
export function caseTicketNote(c: Case, noteAlerts: readonly NoteAlert[] = []): string {
  const lines: string[] = [];
  lines.push(`A.C.O.R.N case${c.caseNumber ? ` ${c.caseNumber}` : ''}: ${c.title.trim()}`);
  if (c.clientName) lines.push(`Client: ${c.clientName}`);
  lines.push(`Severity: ${c.severity}. Status: ${STATUS[c.status] ?? c.status}.`);
  const dates = [['Opened', when(c.createdAt)], ['Resolved', when(c.resolvedAt)], ['Closed', when(c.closedAt)]].filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`);
  if (dates.length > 0) lines.push(`${dates.join('. ')}.`);
  if (c.assignee) lines.push(`Assigned to: ${c.assignee}`);
  const alerts = c.alertCount ?? c.alertIds?.length;
  if (alerts !== undefined) lines.push(`Alerts in this case: ${alerts}`);
  // The alerts by name (the first few), so the ticket says what the case is made of and not only how many.
  const named = noteAlerts.slice(0, MAX_NOTE_ALERTS);
  for (const a of named) lines.push(`- [${a.severity}] ${a.title.trim() || 'Untitled alert'}`);
  if (named.length > 0 && alerts !== undefined && alerts > named.length) lines.push(`- and ${alerts - named.length} more`);
  if (c.description?.trim()) lines.push('', 'What happened:', c.description.trim());
  if (c.resolution?.trim()) lines.push('', 'Resolution:', c.resolution.trim());
  const events = [...(c.timeline ?? [])].filter((e) => when(e.timestamp)).sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
  if (events.length > 0) {
    const shown = events.slice(-MAX_EVENTS);
    lines.push('', events.length > shown.length ? `Timeline (last ${shown.length} of ${events.length}):` : 'Timeline:');
    for (const e of shown) lines.push(`- ${when(e.timestamp)}: ${e.title.trim()}${e.actor ? ` (${e.actor})` : ''}`);
  }
  return lines.join('\n');
}
