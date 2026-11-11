/** After this many days a checked-out item is worth asking after: nothing in the stock has a due date, so "out a long time" is the nearest thing to overdue. */
export const LONG_OUT_DAYS = 30;

/** "Out 45 days" for an item checked out longer than LONG_OUT_DAYS, else null (not checked out, a short time, or a date that cannot be read). Pure. */
export function longOutNote(item: { status: string; checked_out_at: string | null }, now: number = Date.now()): string | null {
  if (item.status !== 'checked_out' || !item.checked_out_at) return null;
  const t = Date.parse(item.checked_out_at);
  if (Number.isNaN(t)) return null;
  const days = Math.floor((now - t) / 86_400_000);
  return days > LONG_OUT_DAYS ? `Out ${days} days` : null;
}

/** How many of the items have been out a long time. */
export function longOutCount(items: { status: string; checked_out_at: string | null }[], now: number = Date.now()): number {
  return items.filter((i) => longOutNote(i, now) !== null).length;
}
