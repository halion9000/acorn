/** The most alerts one "export all" reads: enough for any working filter, small enough for a browser and a spreadsheet. */
export const EXPORT_ALL_CAP = 5000;
/** How many alerts are asked for per request. */
export const EXPORT_PAGE_SIZE = 200;

export interface CollectResult<T> {
  alerts: T[];
  /** How many the filter matches in all, as the server said. */
  total: number;
  /** True when the cap stopped the read before everything was fetched. */
  capped: boolean;
}

/**
 * Every alert the filter matches, read page by page (not only the page on screen), up to a cap. Stops at the server's total, at the cap, or when a page comes back empty (so a wrong total
 * cannot loop for ever). `list` is the page's own list call; the filter's page and page size are replaced.
 */
export async function collectAllAlerts<T, F extends { page?: number; pageSize?: number }>(
  list: (filters: F) => Promise<{ alerts: T[]; total: number }>,
  filters: F,
  cap: number = EXPORT_ALL_CAP,
  pageSize: number = EXPORT_PAGE_SIZE,
): Promise<CollectResult<T>> {
  const out: T[] = [];
  let total = 0;
  for (let page = 1; out.length < cap; page++) {
    const res = await list({ ...filters, page, pageSize });
    total = res.total;
    if (res.alerts.length === 0) break;
    out.push(...res.alerts.slice(0, cap - out.length));
    if (out.length >= total) break;
  }
  return { alerts: out, total, capped: out.length < total && out.length >= cap };
}
