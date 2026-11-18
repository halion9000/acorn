import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const authFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth-session", () => ({ authFetch }));

import { CoreHeartbeat, uptimeText } from "./CoreHeartbeat";

const answer = (b: unknown, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(b) });

beforeEach(() => authFetch.mockReset());

describe("uptimeText", () => {
  it("says days and hours, hours and minutes, minutes, or under a minute", () => {
    expect(uptimeText(30)).toBe("under a minute");
    expect(uptimeText(7 * 60)).toBe("7 min");
    expect(uptimeText(5 * 3600 + 12 * 60)).toBe("5 h 12 min");
    expect(uptimeText(3 * 86400 + 4 * 3600 + 90)).toBe("3 d 4 h");
  });
});

describe("CoreHeartbeat", () => {
  it("shows the commit, the uptime and the feed passes CORE reported", async () => {
    authFetch.mockImplementation(() => answer({ reported: true, reported_at: "2026-11-18T10:00:00Z", commit: "d4c7178", uptime_seconds: 3720, sweeps: 1 }));
    render(<CoreHeartbeat />);
    const line = await screen.findByTestId("core-heartbeat");
    expect(line).toHaveTextContent("CORE runs commit d4c7178, has been up 1 h 2 min and has made 1 feed pass since it started.");
  });

  it("says CORE has not reported when it has not, and shows nothing when the read fails", async () => {
    authFetch.mockImplementation(() => answer({ reported: false, reported_at: null, commit: null, uptime_seconds: null, sweeps: null }));
    const { unmount } = render(<CoreHeartbeat />);
    expect(await screen.findByText(/has not said what it is running lately/)).toBeInTheDocument();
    unmount();
    authFetch.mockImplementation(() => answer({}, false));
    render(<CoreHeartbeat />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("core-heartbeat")).toBeNull();
  });
});
