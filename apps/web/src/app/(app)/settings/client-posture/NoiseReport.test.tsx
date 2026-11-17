import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth-session", () => ({ authFetch }));

import { NoiseReport } from "./NoiseReport";

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("Noisy rules on a client", () => {
  beforeEach(() => authFetch.mockReset());

  it("lists the rules with their counts and a suggestion where almost all were quiet, and asks again for another period", async () => {
    authFetch.mockImplementation(() => json({ days: 30, total_alerts: 120, rules: [
      { rule: "Impossible travel", total: 40, quiet: 38, quiet_percent: 95, with_ticket: 1, suggestion: "95% of its 40 alerts ended with nothing done. Consider tuning the rule or hiding this alert type." },
      { rule: "New device", total: 100, quiet: 12, quiet_percent: 12, with_ticket: 30, suggestion: null },
    ] }));
    render(<NoiseReport clientId="c 1" />);
    const table = await screen.findByTestId("noise-table");
    expect(table).toHaveTextContent("Impossible travel");
    expect(table).toHaveTextContent("95% of its 40 alerts ended with nothing done");
    expect(screen.getByText("New device").closest("tr")).not.toHaveTextContent("Consider tuning");
    expect(authFetch).toHaveBeenCalledWith("/api/v1/alerts/noise?client_id=c%201&days=30");
    await userEvent.click(screen.getByRole("button", { name: "90 days" }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/api/v1/alerts/noise?client_id=c%201&days=90"));
  });

  it("says so when there were no alerts, when none were quiet, and when the answer is refused", async () => {
    authFetch.mockImplementation(() => json({ days: 30, total_alerts: 0, rules: [] }));
    const first = render(<NoiseReport clientId="c1" />);
    expect(await screen.findByTestId("noise-empty")).toHaveTextContent("No alerts in the last 30 days.");
    first.unmount();
    authFetch.mockImplementation(() => json({ days: 30, total_alerts: 12, rules: [] }));
    const second = render(<NoiseReport clientId="c1" />);
    expect(await screen.findByTestId("noise-empty")).toHaveTextContent("None of the 12 alerts of the last 30 days ended with nothing done.");
    second.unmount();
    authFetch.mockImplementation(() => json({}, 403));
    render(<NoiseReport clientId="c1" />);
    expect(await screen.findByTestId("noise-empty")).toBeInTheDocument();
  });
});
