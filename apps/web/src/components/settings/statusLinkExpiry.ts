/** How long before a client status link stops working to start saying so: long enough to send the client a new one. */
export const STATUS_LINK_WARNING_DAYS = 7;

const DAY = 86_400_000;

/** "Expires today" / "Expires in 3 days" for a link that is live and close to its end, or null for one that is far off, already expired, revoked, or whose date cannot be read. */
export function statusLinkExpiryNote(link: { state: string; expires_at: string }, now: number = Date.now()): string | null {
  if (link.state !== 'live') return null;
  const end = Date.parse(link.expires_at);
  if (Number.isNaN(end) || end <= now) return null;
  const left = Math.floor((end - now) / DAY);
  if (left > STATUS_LINK_WARNING_DAYS) return null;
  return left === 0 ? 'Expires today' : `Expires in ${left} day${left === 1 ? '' : 's'}`;
}
