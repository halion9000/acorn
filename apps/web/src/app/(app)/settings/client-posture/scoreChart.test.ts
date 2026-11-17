import { describe, expect, it } from "vitest";
import { CHART_H, CHART_W, PAD, changeText, chartPoints, linePath, yOf } from "./scoreChart";

describe("the score history chart", () => {
  const rows = [{ day: "2026-11-03", score: 80 }, { day: "2026-11-01", score: 60 }, { day: "2026-11-02", score: null }, { day: "2026-11-04", score: 100 }];

  it("puts the scored days in date order, spread across the width, with a higher score higher up", () => {
    const pts = chartPoints(rows);
    expect(pts.map((p) => p.day)).toEqual(["2026-11-01", "2026-11-03", "2026-11-04"]);
    expect(pts[0]!.x).toBe(PAD.left);
    expect(pts[2]!.x).toBe(CHART_W - PAD.right);
    expect(pts[0]!.y).toBeGreaterThan(pts[1]!.y);
    expect(pts[2]!.y).toBe(PAD.top);
    expect(chartPoints([{ day: "d", score: 0 }])[0]!.y).toBe(CHART_H - PAD.bottom);
  });

  it("draws a lone day as one point in the middle, nothing for no scores, and keeps a wild score inside the drawing", () => {
    expect(chartPoints([{ day: "d", score: 50 }])[0]!.x).toBe(PAD.left + (CHART_W - PAD.left - PAD.right) / 2);
    expect(chartPoints([{ day: "d", score: null }])).toEqual([]);
    expect(chartPoints([{ day: "d", score: 250 }])[0]!.y).toBe(PAD.top);
    expect(linePath([])).toBe("");
  });

  it("writes the line as a path through every point and the target at its own height", () => {
    const path = linePath(chartPoints(rows));
    expect(path.startsWith("M34 ")).toBe(true);
    expect(path.match(/L/g)).toHaveLength(2);
    expect(yOf(100)).toBe(PAD.top);
    expect(yOf(0)).toBe(CHART_H - PAD.bottom);
    expect(yOf(50)).toBe((PAD.top + CHART_H - PAD.bottom) / 2);
  });

  it("says in words how far the score moved", () => {
    expect(changeText(chartPoints(rows))).toBe("up 40 points");
    expect(changeText(chartPoints([{ day: "a", score: 70 }, { day: "b", score: 69 }]))).toBe("down 1 point");
    expect(changeText(chartPoints([{ day: "a", score: 70 }, { day: "b", score: 70 }]))).toBe("no change");
    expect(changeText(chartPoints([{ day: "a", score: 70 }]))).toBe("");
  });
});
