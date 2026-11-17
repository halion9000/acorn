import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth-session", () => ({ authFetch }));

import { ScoreHistory } from "./ScoreHistory";

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("Score over time", () => {
  beforeEach(() => authFetch.mockReset());

  it("draws the line from the client's history, says how far it moved, and asks again for another period", async () => {
    authFetch.mockImplementation(() => json({ rows: [{ day: "2026-10-01", score: 60 }, { day: "2026-10-15", score: 72 }, { day: "2026-11-01", score: 75 }] }));
    render(<ScoreHistory clientId="c 1" />);
    expect(await screen.findByTestId("score-history-change")).toHaveTextContent("75% now, up 15 points since 2026-10-01.");
    expect(document.querySelectorAll("circle")).toHaveLength(3);
    expect(authFetch).toHaveBeenCalledWith("/api/v1/client-posture/c%201/score-history?days=90");
    await userEvent.click(screen.getByRole("button", { name: "1 year" }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/api/v1/client-posture/c%201/score-history?days=365"));
  });

  it("says there is no history yet, both for an empty answer and for a refused one", async () => {
    authFetch.mockImplementation(() => json({ rows: [] }));
    const { unmount } = render(<ScoreHistory clientId="c1" />);
    expect(await screen.findByTestId("score-history-empty")).toBeInTheDocument();
    unmount();
    authFetch.mockImplementation(() => json({}, 403));
    render(<ScoreHistory clientId="c1" />);
    expect(await screen.findByTestId("score-history-empty")).toBeInTheDocument();
  });
});
