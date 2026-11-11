import { describe, expect, it, vi } from 'vitest';
import { collectAllAlerts } from './collectAlerts';

const server = (count: number) =>
  vi.fn(async (f: { page?: number; pageSize?: number; status?: string }) => {
    const size = f.pageSize ?? 50;
    const start = ((f.page ?? 1) - 1) * size;
    return { alerts: Array.from({ length: Math.max(0, Math.min(size, count - start)) }, (_, i) => start + i), total: count };
  });

describe('collectAllAlerts', () => {
  it('reads every page the filter matches, keeping the filter and replacing only the paging', async () => {
    const list = server(450);
    const out = await collectAllAlerts(list, { status: 'open', page: 3, pageSize: 25 }, 5000, 200);
    expect(out.alerts).toHaveLength(450);
    expect(out.alerts[0]).toBe(0);
    expect(out.alerts[449]).toBe(449);
    expect([out.total, out.capped]).toEqual([450, false]);
    expect(list.mock.calls.map((c) => c[0])).toEqual([
      { status: 'open', page: 1, pageSize: 200 },
      { status: 'open', page: 2, pageSize: 200 },
      { status: 'open', page: 3, pageSize: 200 },
    ]);
  });

  it('stops at the cap and says so', async () => {
    const out = await collectAllAlerts(server(1000), {}, 300, 200);
    expect(out.alerts).toHaveLength(300);
    expect([out.total, out.capped]).toEqual([1000, true]);
  });

  it('stops when a page comes back empty even if the total says there is more, and handles nothing at all', async () => {
    const lying = vi.fn(async (f: { page?: number }) => ({ alerts: (f.page ?? 1) === 1 ? [1, 2] : [], total: 99 }));
    const out = await collectAllAlerts(lying, {}, 5000, 200);
    expect(out.alerts).toEqual([1, 2]);
    expect(lying).toHaveBeenCalledTimes(2);
    const none = await collectAllAlerts(server(0), {});
    expect([none.alerts.length, none.total, none.capped]).toEqual([0, 0, false]);
  });
});
