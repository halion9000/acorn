import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/api", () => ({ scriptRunsApi: { list: api.list } }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { ScriptLog } from "./ScriptLog";

const run = (over: Record<string, unknown> = {}) => ({
  id: "s1",
  requested_at: "2026-11-16T10:05:00Z",
  finished_at: "2026-11-16T10:06:00Z",
  status: "done",
  outcome: "done",
  script: "Disk Space Scan",
  device: "PC-01",
  client_name: "Acme Dental",
  alert_id: "a1",
  alert_title: "Low disk space",
  message: "Script finished with exit code 0.",
  by: "person",
  ...over,
});
const list = (items = [run()], over: Record<string, unknown> = {}) => ({ items, done: 1, failed: 0, waiting: 0, total: items.length, days: 30, ...over });

beforeEach(() => {
  api.list.mockReset();
  api.list.mockResolvedValue(list());
});

describe("ScriptLog", () => {
  it("lists each script with when, who asked, the machine and client, the result and a link to its alert", async () => {
    render(<ScriptLog />);
    const row = await screen.findByTestId("script-log-row");
    expect(row).toHaveTextContent("2026-11-16 10:05");
    expect(row).toHaveTextContent("by a person");
    expect(row).toHaveTextContent("Disk Space Scan");
    expect(row).toHaveTextContent("PC-01");
    expect(row).toHaveTextContent("Acme Dental");
    expect(row).toHaveTextContent("Ran");
    expect(row).toHaveTextContent("Script finished with exit code 0.");
    expect(within(row).getByRole("link", { name: "Low disk space" })).toHaveAttribute("href", "/alerts/a1");
  });

  it("says in words why a script never ran, and tells a rule from a person", async () => {
    api.list.mockResolvedValue(
      list([run({ id: "s2", status: "expired", outcome: "failed", by: "rule", alert_id: null, message: "CORE did not collect this request within 30 minutes, so it was never run." })], { done: 0, failed: 1 }),
    );
    render(<ScriptLog />);
    const row = await screen.findByTestId("script-log-row");
    expect(row).toHaveTextContent("Never collected");
    expect(row).toHaveTextContent("by a rule");
    expect(row).toHaveTextContent("never run");
    expect(within(row).queryByRole("link")).toBeNull();
  });

  it("has a tab for each outcome with its count, and asks the server for just that outcome", async () => {
    api.list.mockResolvedValue(list([run()], { done: 7, failed: 2, waiting: 1 }));
    render(<ScriptLog />);
    expect(await screen.findByRole("tab", { name: "All (10)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Did not run (2)" })).toBeTruthy();
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(""));
    await userEvent.click(screen.getByRole("tab", { name: "Did not run (2)" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("failed"));
    await userEvent.click(screen.getByRole("tab", { name: "Waiting (1)" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("waiting"));
  });

  it("says when there is nothing, when the list was cut, and when it cannot be read", async () => {
    api.list.mockResolvedValueOnce(list([], { done: 0 }));
    const a = render(<ScriptLog />);
    expect(await screen.findByTestId("script-log-empty")).toHaveTextContent("No scripts here.");
    a.unmount();
    api.list.mockResolvedValueOnce(list([run()], { total: 450 }));
    const b = render(<ScriptLog />);
    expect(await screen.findByText("Showing the newest 1 of 450.")).toBeTruthy();
    b.unmount();
    api.list.mockRejectedValueOnce(new Error("The API answered 500"));
    render(<ScriptLog />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API answered 500");
  });
});
