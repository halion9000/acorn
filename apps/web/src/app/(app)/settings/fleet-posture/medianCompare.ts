/**
 * How a client's score sits against the fleet: the middle score of every client that has one, and each client's distance from it in points. The median (not the average) so one very low or very
 * high client does not move the line everyone is measured against. Pure.
 */

/** The middle of the scores (the mean of the two middle ones for an even count), rounded to a whole point; null with no scores. */
export function fleetMedian(scores: (number | null | undefined)[]): number | null {
  const s = scores.filter((n): n is number => typeof n === "number" && Number.isFinite(n)).sort((a, b) => a - b);
  if (s.length === 0) return null;
  const mid = s.length >> 1;
  return Math.round(s.length % 2 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2);
}

/** Points above (positive) or below (negative) the median; null when either is unknown. */
export function vsMedian(score: number | null | undefined, median: number | null): number | null {
  return typeof score === "number" && median !== null ? Math.round(score) - median : null;
}

/** "+4", "-7" or "same", for display; empty when unknown. */
export function vsMedianText(delta: number | null): string {
  if (delta === null) return "";
  return delta === 0 ? "same" : delta > 0 ? `+${delta}` : `${delta}`;
}
