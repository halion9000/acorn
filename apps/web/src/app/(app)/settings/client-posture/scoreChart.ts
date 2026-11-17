/**
 * The geometry of a client's score history as a line chart: each day's score as a point, scaled to a fixed drawing (0 to 100 up the side, the days spread across). Pure, so the lines are tested
 * without a browser. A day with no score is skipped, and a single day is drawn as a lone point.
 */

export interface ScoreDay {
  day: string;
  score: number | null;
}

export interface ChartPoint {
  day: string;
  score: number;
  x: number;
  y: number;
}

export const CHART_W = 600;
export const CHART_H = 160;
export const PAD = { left: 34, right: 12, top: 10, bottom: 22 };

/** The scored days as points, in date order (pure). Scores are kept to 0 to 100. */
export function chartPoints(rows: ScoreDay[], w = CHART_W, h = CHART_H): ChartPoint[] {
  const scored = rows.filter((r): r is { day: string; score: number } => typeof r.score === "number" && Number.isFinite(r.score)).sort((a, b) => a.day.localeCompare(b.day));
  const inner = { w: w - PAD.left - PAD.right, h: h - PAD.top - PAD.bottom };
  return scored.map((r, i) => {
    const s = Math.max(0, Math.min(100, r.score));
    return {
      day: r.day,
      score: r.score,
      x: scored.length === 1 ? PAD.left + inner.w / 2 : PAD.left + (i / (scored.length - 1)) * inner.w,
      y: PAD.top + (1 - s / 100) * inner.h,
    };
  });
}

/** The SVG path of the line through the points ("" for none). */
export function linePath(points: ChartPoint[]): string {
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${Math.round(p.x * 10) / 10} ${Math.round(p.y * 10) / 10}`).join("");
}

/** The y position of a score on the drawing, for the target line (pure). */
export function yOf(score: number, h = CHART_H): number {
  const inner = h - PAD.top - PAD.bottom;
  return PAD.top + (1 - Math.max(0, Math.min(100, score)) / 100) * inner;
}

/** The change from the first to the last scored day in words: "up 6 points", "down 3 points", "no change"; "" with fewer than two days (pure). */
export function changeText(points: ChartPoint[]): string {
  if (points.length < 2) return "";
  const d = points[points.length - 1]!.score - points[0]!.score;
  return d === 0 ? "no change" : `${d > 0 ? "up" : "down"} ${Math.abs(d)} point${Math.abs(d) === 1 ? "" : "s"}`;
}
