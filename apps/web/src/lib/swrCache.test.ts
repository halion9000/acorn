import { describe, expect, it, vi } from 'vitest';
import { createSwrCache } from './swrCache';

const store = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m };
};

describe('createSwrCache', () => {
  it('reads once, serves the next calls from memory while fresh, and shares a read that is in flight', async () => {
    let t = 0;
    const load = vi.fn(async () => ['a']);
    const c = createSwrCache(load, { key: 'k', ttlMs: 1000, now: () => t, storage: null });
    const [x, y] = await Promise.all([c.get(), c.get()]);
    expect(x).toEqual(['a']);
    expect(y).toBe(x);
    expect(load).toHaveBeenCalledTimes(1);
    t = 500;
    await c.get();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('after the time is up it waits for the read when nothing is stored, and refreshes in the background when a copy is', async () => {
    let t = 0;
    let n = 0;
    const load = vi.fn(async () => [`v${++n}`]);
    const s = store();
    const c = createSwrCache(load, { key: 'k', ttlMs: 1000, now: () => t, storage: s });
    expect(await c.get()).toEqual(['v1']);
    t = 5000;
    expect(await c.get()).toEqual(['v1']); // the stale copy at once
    await Promise.resolve();
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(2);
    expect(await c.get()).toEqual(['v2']); // the refresh landed
  });

  it('a new tab with a stored copy answers at once, and a failed refresh keeps the copy', async () => {
    const s = store();
    s.setItem('k', JSON.stringify({ at: 1, value: ['stored'] }));
    const load = vi.fn(async () => {
      throw new Error('slow API down');
    });
    const c = createSwrCache(load, { key: 'k', ttlMs: 1000, now: () => 99999, storage: s });
    expect(await c.get()).toEqual(['stored']);
    expect(await c.get()).toEqual(['stored']);
  });

  it('without a stored copy a failed read is the caller\'s error, and clear forgets the copy', async () => {
    const s = store();
    const c = createSwrCache(async () => { throw new Error('nope'); }, { key: 'k', ttlMs: 1000, storage: s });
    await expect(c.get()).rejects.toThrow('nope');
    s.setItem('k', JSON.stringify({ at: 1, value: [1] }));
    c.clear();
    expect(s.m.has('k')).toBe(false);
  });

  it('ignores a damaged stored copy', async () => {
    const s = store();
    s.setItem('k', '{not json');
    const c = createSwrCache(async () => ['fresh'], { key: 'k', ttlMs: 10, storage: s });
    expect(await c.get()).toEqual(['fresh']);
  });
});
