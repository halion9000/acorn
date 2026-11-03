/** What is worth saying about an API key at a glance: it has expired, it is about to, or nothing has used it for a long time (a key nobody uses is a key nobody would notice being stolen). */
export const EXPIRY_WARNING_DAYS = 30;
export const UNUSED_AFTER_DAYS = 90;

export interface KeyTiming {
  createdAt: string;
  lastUsedAt?: string | null;
  expiresAt?: string | null;
}

export interface KeyHealth {
  text: string;
  tone: 'bad' | 'warn';
}

const DAY = 86_400_000;
const days = (ms: number) => Math.floor(ms / DAY);
const time = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
};

/** The most important thing to say about the key, or null when there is nothing. An expired key outranks everything; then one expiring soon; then one that has not been used. */
export function keyHealth(k: KeyTiming, now: number = Date.now()): KeyHealth | null {
  const expires = time(k.expiresAt);
  if (expires !== null) {
    if (expires <= now) return { text: 'Expired', tone: 'bad' };
    const left = days(expires - now);
    if (left <= EXPIRY_WARNING_DAYS) return { text: left === 0 ? 'Expires today' : `Expires in ${left} day${left === 1 ? '' : 's'}`, tone: 'warn' };
  }
  const used = time(k.lastUsedAt);
  const created = time(k.createdAt);
  if (used !== null) {
    const idle = days(now - used);
    if (idle >= UNUSED_AFTER_DAYS) return { text: `Not used for ${idle} days`, tone: 'warn' };
  } else if (created !== null) {
    const age = days(now - created);
    if (age >= UNUSED_AFTER_DAYS) return { text: `Never used, made ${age} days ago`, tone: 'warn' };
  }
  return null;
}
