/** After this many days without a sign-in an active account is worth a second look: it is a way in that nobody is using. */
export const QUIET_ACCOUNT_DAYS = 90;

const DAY = 86_400_000;

/**
 * "Never signed in" or "No sign-in for 120 days" for an active account that has been quiet too long, or null for one in use, one switched off (it cannot sign in anyway), or one made in the last
 * 90 days that has not signed in yet (a new account is not a quiet one). Pure.
 */
export function quietAccountNote(member: { is_active: boolean; last_login: string | null; created_at: string }, now: number = Date.now()): string | null {
  if (!member.is_active) return null;
  if (member.last_login === null) {
    const made = Date.parse(member.created_at);
    if (Number.isNaN(made) || now - made <= QUIET_ACCOUNT_DAYS * DAY) return null;
    return 'Never signed in';
  }
  const last = Date.parse(member.last_login);
  if (Number.isNaN(last)) return null;
  const days = Math.floor((now - last) / DAY);
  return days > QUIET_ACCOUNT_DAYS ? `No sign-in for ${days} days` : null;
}

/** The members with the longest since a sign-in first: never signed in at the top, then the oldest sign-in. The input is not changed; members with the same time keep their order. Pure. */
export function byQuietest<T extends { last_login: string | null }>(members: readonly T[]): T[] {
  const when = (m: T): number => {
    if (m.last_login === null) return -Infinity;
    const t = Date.parse(m.last_login);
    return Number.isNaN(t) ? -Infinity : t;
  };
  return members.map((m, i) => ({ m, i })).sort((a, b) => when(a.m) - when(b.m) || a.i - b.i).map((x) => x.m);
}
