import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({ list: vi.fn(), turnOff: vi.fn(), toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/api", () => ({ scriptRulesApi: { list: api.list, turnOff: api.turnOff } }));
vi.mock("react-hot-toast", () => ({ default: api.toast }));

import { ScriptRules } from "./ScriptRules";

const rule = (over: Record<string, unknown> = {}) => ({
  id: "r1", scope: "client", client_name: "Acme", source: "aisoc-remote-tools", title: "ScreenConnect for another server", windows_script: "Remove rogue SC (Windows)", mac_script: null, requires_tool: "screenconnect", created_at: "2026-11-07T12:00:00Z", active: true, ...over,
});

beforeEach(() => {
  api.list.mockReset();
  api.turnOff.mockReset();
  api.toast.error.mockReset();
});

describe("ScriptRules", () => {
  it("lists each rule with its scripts per system, the condition, who it covers and since when", async () => {
    api.list.mockResolvedValue([rule(), rule({ id: "r2", scope: "all", client_name: null, requires_tool: null, mac_script: "Remove rogue SC (Mac)", windows_script: null })]);
    render(<ScriptRules />);
    const rows = await screen.findAllByTestId("script-rule-row");
    expect(rows[0]).toHaveTextContent("Windows: Remove rogue SC (Windows) · Mac: none · only if the client uses screenconnect");
    expect(rows[0]).toHaveTextContent("Acme · aisoc-remote-tools · since 2026-11-07");
    expect(rows[1]).toHaveTextContent("Windows: none · Mac: Remove rogue SC (Mac)");
    expect(rows[1]).toHaveTextContent("every client");
  });

  it("says when there are none and when the list cannot be read", async () => {
    api.list.mockResolvedValueOnce([]);
    const a = render(<ScriptRules />);
    expect(await screen.findByText("No rules yet.")).toBeInTheDocument();
    a.unmount();
    api.list.mockRejectedValueOnce(new Error("The API answered 500"));
    render(<ScriptRules />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API answered 500");
  });

  it("turns a rule off and removes it, and says so when that fails", async () => {
    api.list.mockResolvedValue([rule(), rule({ id: "r2", title: "Another" })]);
    api.turnOff.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("No such active rule"));
    const user = userEvent.setup();
    render(<ScriptRules />);
    await user.click(await screen.findByRole("button", { name: "Turn off the script rule for ScreenConnect for another server" }));
    await waitFor(() => expect(screen.queryByText("ScreenConnect for another server")).not.toBeInTheDocument());
    expect(api.turnOff).toHaveBeenCalledWith("r1");
    await user.click(screen.getByRole("button", { name: "Turn off the script rule for Another" }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith("No such active rule"));
    expect(screen.getByText("Another")).toBeInTheDocument();
  });
});
