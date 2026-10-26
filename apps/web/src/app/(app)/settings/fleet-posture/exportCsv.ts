/**
 * The fleet page as spreadsheets: the worst-clients table and any board. Evidence text comes from monitored systems, so a cell that would be read as a formula by a spreadsheet (it starts with
 * =, +, - or @) is written with a leading apostrophe instead of being left to run.
 */
import type { BoardRow, FleetClient } from './FleetPosture';

export function csvCell(v: string | number | boolean | null | undefined): string {
  let s = v === null || v === undefined ? '' : String(v);
  if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const line = (cells: (string | number | boolean | null | undefined)[]): string => cells.map(csvCell).join(',');

export function worstCsv(clients: FleetClient[]): string {
  const head = ['Client', 'Score %', 'Target %', 'Below target', 'Fine', 'Needs attention', 'Problems', 'Accepted', 'Tools not updating'];
  const rows = clients.map((c) => line([c.client_name ?? c.client_id, c.score, c.target ?? '', c.below_target ? 'yes' : '', c.met, c.partly, c.not_met, c.accepted, c.stale_tools.join('; ')]));
  return [line(head), ...rows].join('\n') + '\n';
}

export function boardCsv(rows: BoardRow[]): string {
  const head = ['Client', 'Tool', 'Check', 'Status', 'What it saw', 'Since', 'Accepted', 'Owner', 'Due', 'Overdue', 'Items'];
  const lines = rows.map((r) => line([r.client_name, r.source, r.key, r.status, r.evidence, r.since ?? '', r.accepted ? 'yes' : '', r.owner ?? '', r.due_date ?? '', r.overdue ? 'yes' : '', (r.items ?? []).join('; ')]));
  return [line(head), ...lines].join('\n') + '\n';
}

export function downloadCsv(name: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
