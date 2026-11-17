import { describe, expect, it } from "vitest";
import { fleetMedian, vsMedian, vsMedianText } from "./medianCompare";

describe("the fleet median", () => {
  it("is the middle score, the mean of the two middle ones for an even count, and ignores clients with no score", () => {
    expect(fleetMedian([90, 10, 70])).toBe(70);
    expect(fleetMedian([80, 60, 100, 40])).toBe(70);
    expect(fleetMedian([81, 82])).toBe(82);
    expect(fleetMedian([null, 50, undefined])).toBe(50);
    expect(fleetMedian([])).toBeNull();
    expect(fleetMedian([null])).toBeNull();
  });
  it("is not moved by one very low client, unlike the average", () => {
    expect(fleetMedian([80, 82, 84, 86, 0])).toBe(82);
  });
});

describe("a client against the median", () => {
  it("is the difference in points, and unknown when the score or the median is", () => {
    expect(vsMedian(75, 70)).toBe(5);
    expect(vsMedian(60, 70)).toBe(-10);
    expect(vsMedian(70, 70)).toBe(0);
    expect(vsMedian(null, 70)).toBeNull();
    expect(vsMedian(70, null)).toBeNull();
  });
  it("reads as a signed number, same, or nothing", () => {
    expect([vsMedianText(5), vsMedianText(-10), vsMedianText(0), vsMedianText(null)]).toEqual(["+5", "-10", "same", ""]);
  });
});
