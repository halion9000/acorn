/** How old a control's newest accepted evidence may be before it is worth refreshing: a year, the usual audit period. */
export const EVIDENCE_MAX_AGE_DAYS = 365;

const DAY = 86_400_000;

/** The age in whole days of the newest accepted evidence, or null when none is accepted or no date can be read (pure). */
export function newestAcceptedAgeDays(items: { status: string; collected_at: string }[], now: number = Date.now()): number | null {
  let newest = -Infinity;
  for (const e of items) {
    if (e.status !== 'accepted') continue;
    const t = Date.parse(e.collected_at);
    if (!Number.isNaN(t) && t > newest) newest = t;
  }
  return newest === -Infinity ? null : Math.max(0, Math.floor((now - newest) / DAY));
}

/** "Accepted evidence is 14 months old: refresh it" once it is past a year, else null (pure). */
export function evidenceAgeNote(items: { status: string; collected_at: string }[], now: number = Date.now()): string | null {
  const days = newestAcceptedAgeDays(items, now);
  if (days === null || days <= EVIDENCE_MAX_AGE_DAYS) return null;
  const months = Math.floor(days / 30.4);
  return `The newest accepted evidence is ${months} months old: refresh it.`;
}

/** How many of the controls (each given as its own evidence list) have accepted evidence past a year. */
export function staleControlCount(perControl: { status: string; collected_at: string }[][], now: number = Date.now()): number {
  return perControl.filter((items) => evidenceAgeNote(items, now) !== null).length;
}
