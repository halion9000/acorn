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
