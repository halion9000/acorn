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

/**
 * A case as plain text for a ticket note (HaloPSA or any other): what it is, where it stands, what was done. Plain lines only, no markup, so it pastes cleanly; a field the case does not have
 * is left out rather than shown empty.
 */
export function caseTicketNote(c: Case): string {
  const lines: string[] = [];
  lines.push(`A.C.O.R.N case${c.caseNumber ? ` ${c.caseNumber}` : ''}: ${c.title.trim()}`);
  if (c.clientName) lines.push(`Client: ${c.clientName}`);
  lines.push(`Severity: ${c.severity}. Status: ${STATUS[c.status] ?? c.status}.`);
  const dates = [['Opened', when(c.createdAt)], ['Resolved', when(c.resolvedAt)], ['Closed', when(c.closedAt)]].filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`);
  if (dates.length > 0) lines.push(`${dates.join('. ')}.`);
  if (c.assignee) lines.push(`Assigned to: ${c.assignee}`);
  const alerts = c.alertCount ?? c.alertIds?.length;
  if (alerts !== undefined) lines.push(`Alerts in this case: ${alerts}`);
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
