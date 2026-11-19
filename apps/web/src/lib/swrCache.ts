/**
 * A small stale-while-revalidate cache for one slow, rarely changing read (the client list, which took 6.6 s and held up every Compliance, finance and metrics page).
 *
 * ``get()`` returns the value in memory while it is fresh (within ``ttlMs``); otherwise, when a copy from earlier in this browser session is stored, it returns THAT at once and refreshes in the background so the
 * next call has the new one; with nothing stored it waits for the read. Two calls at the same time share one read. A failed refresh keeps what was stored. ``clear()`` forgets everything (sign-out).
 */
export interface SwrCacheOptions {
  key: string;
  ttlMs: number;
  now?: () => number;
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null;
}

export interface SwrCache<T> {
  get(): Promise<T>;
  clear(): void;
}

export function createSwrCache<T>(load: () => Promise<T>, opts: SwrCacheOptions): SwrCache<T> {
  const now = opts.now ?? Date.now;
  let memory: { at: number; value: T } | null = null;
  let inflight: Promise<T> | null = null;

  const readStored = (): { at: number; value: T } | null => {
    try {
      const raw = opts.storage?.getItem(opts.key);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as { at?: unknown; value?: unknown };
      return typeof parsed.at === 'number' ? { at: parsed.at, value: parsed.value as T } : null;
    } catch {
      return null;
    }
  };

  const refresh = (): Promise<T> => {
    if (inflight) return inflight;
    const p = load()
      .then((value) => {
        memory = { at: now(), value };
        try {
          opts.storage?.setItem(opts.key, JSON.stringify(memory));
        } catch {
          /* storage full or unavailable: memory still serves this tab */
        }
        return value;
      })
      .finally(() => {
        inflight = null;
      });
    inflight = p;
    return p;
  };

  return {
    get() {
      if (memory && now() - memory.at < opts.ttlMs) return Promise.resolve(memory.value);
      const stored = memory ?? readStored();
      if (stored) {
        memory = stored;
        void refresh().catch(() => undefined); // a failed refresh keeps the copy we have
        return Promise.resolve(stored.value);
      }
      return refresh();
    },
    clear() {
      memory = null;
      inflight = null;
      try {
        opts.storage?.removeItem(opts.key);
      } catch {
        /* nothing to clear */
      }
    },
  };
}
