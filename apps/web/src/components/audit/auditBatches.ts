export interface BatchableEvent {
  id: string;
  action: string;
  changes: Record<string, unknown> | null;
}

export interface FoldedRow<T extends BatchableEvent> {
  /** The first event of the run (the newest, as the list is newest first). */
  event: T;
  /** How many events the row stands for (1 for an ordinary event). */
  count: number;
  /** The batch id the run shares, or null for an ordinary event. */
  batch: string | null;
}

function batchOf(e: BatchableEvent): string | null {
  const b = e.changes?.batch;
  return typeof b === 'string' && b !== '' ? b : null;
}

/**
 * The page's events with each run of one bulk action folded into a single row: events next to each other that share a batch id and an action (one click that closed 180 alerts) become one row with a
 * count. A batch whose id is in `open` is left unfolded. Order is kept; nothing is dropped. Pure.
 */
export function foldBatches<T extends BatchableEvent>(items: T[], open: ReadonlySet<string> = new Set()): FoldedRow<T>[] {
  const rows: FoldedRow<T>[] = [];
  for (const e of items) {
    const batch = batchOf(e);
    const last = rows[rows.length - 1];
    if (batch !== null && !open.has(batch) && last && last.batch === batch && last.event.action === e.action) last.count += 1;
    else rows.push({ event: e, count: 1, batch });
  }
  return rows;
}
