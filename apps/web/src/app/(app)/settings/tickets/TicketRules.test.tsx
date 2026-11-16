import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({ list: vi.fn(), turnOff: vi.fn(), changeNote: vi.fn(), toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/api", () => ({ ticketRulesApi: { list: api.list, turnOff: api.turnOff, changeNote: api.changeNote } }));
vi.mock("react-hot-toast", () => ({ default: api.toast }));

import { TicketRules } from "./TicketRules";

const rule = (over: Record<string, unknown> = {}) => ({ id: "r1", scope: "client", client_name: "Pirkey Barber PLLC", source: "cipp", title: 'A user asked to release a quarantined message: "x"', created_at: "2026-11-05T12:00:00Z", active: true, ...over });

beforeEach(() => {
  api.list.mockReset();
  api.turnOff.mockReset();
  api.changeNote.mockReset();
  api.toast.error.mockReset();
});

describe("TicketRules", () => {
  it("lists each rule with its type, who it covers, the tool and since when", async () => {
    api.list.mockResolvedValue([rule(), rule({ id: "r2", scope: "all", client_name: null, source: null, title: "Disk space low" })]);
    render(<TicketRules />);
    const rows = await screen.findAllByTestId("ticket-rule-row");
    expect(rows[0]).toHaveTextContent("Pirkey Barber PLLC · cipp · since 2026-11-05");
    expect(rows[1]).toHaveTextContent("Disk space low");
    expect(rows[1]).toHaveTextContent("every client · since 2026-11-05");
  });

  it("says when there are none, and when the list cannot be read", async () => {
    api.list.mockResolvedValueOnce([]);
    const a = render(<TicketRules />);
    expect(await screen.findByText("No rules yet.")).toBeInTheDocument();
    a.unmount();
    api.list.mockRejectedValueOnce(new Error("The API answered 500"));
    render(<TicketRules />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API answered 500");
  });

  it("turns a rule off and removes it from the list, and says so when that fails", async () => {
    api.list.mockResolvedValue([rule(), rule({ id: "r2", title: "Disk space low" })]);
    api.turnOff.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("No such active rule"));
    const user = userEvent.setup();
    render(<TicketRules />);
    await screen.findAllByTestId("ticket-rule-row");
    await user.click(screen.getByRole("button", { name: /Turn off the rule for A user asked/ }));
    await waitFor(() => expect(screen.getAllByTestId("ticket-rule-row")).toHaveLength(1));
    expect(api.turnOff).toHaveBeenCalledWith("r1");
    await user.click(screen.getByRole("button", { name: "Turn off the rule for Disk space low" }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith("No such active rule"));
    expect(screen.getAllByTestId("ticket-rule-row")).toHaveLength(1);
  });
});

describe("the note of a rule", () => {
  it("shows the note a rule writes into its tickets, or says there is none", async () => {
    api.list.mockResolvedValue([rule({ note: "Call the client first." }), rule({ id: "r2", title: "Disk space low" })]);
    render(<TicketRules />);
    const notes = await screen.findAllByTestId("ticket-rule-note");
    expect(notes[0]).toHaveTextContent("Note for the ticket: Call the client first.");
    expect(notes[1]).toHaveTextContent("No note for the ticket.");
  });

  it("edits the note, saves it for that rule, and shows it", async () => {
    api.list.mockResolvedValue([rule({ note: "old" })]);
    api.changeNote.mockResolvedValue(rule({ note: "Reboot, then close." }));
    render(<TicketRules />);
    await userEvent.click(await screen.findByRole("button", { name: /Edit the note of the rule/ }));
    const box = screen.getByLabelText(/Note for the rule/);
    await userEvent.clear(box);
    await userEvent.type(box, "  Reboot, then close.  ");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(api.changeNote).toHaveBeenCalledWith("r1", "Reboot, then close."));
    expect(await screen.findByTestId("ticket-rule-note")).toHaveTextContent("Note for the ticket: Reboot, then close.");
  });

  it("sends nothing when the note was not changed, and clears a note when the box is emptied", async () => {
    api.list.mockResolvedValue([rule({ note: "old note" })]);
    api.changeNote.mockResolvedValue(rule({ note: "" }));
    render(<TicketRules />);
    await userEvent.click(await screen.findByRole("button", { name: /Edit the note of the rule/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(api.changeNote).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Edit the note of the rule/ }));
    await userEvent.clear(screen.getByLabelText(/Note for the rule/));
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(api.changeNote).toHaveBeenCalledWith("r1", ""));
    expect(await screen.findByTestId("ticket-rule-note")).toHaveTextContent("No note for the ticket.");
  });

  it("says so when the note could not be saved and keeps the box open", async () => {
    api.list.mockResolvedValue([rule()]);
    api.changeNote.mockRejectedValue(new Error("Ticket rule not found"));
    render(<TicketRules />);
    await userEvent.click(await screen.findByRole("button", { name: /Edit the note of the rule/ }));
    await userEvent.type(screen.getByLabelText(/Note for the rule/), "Close it");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith("Ticket rule not found"));
    expect(screen.getByLabelText(/Note for the rule/)).toBeInTheDocument();
  });
});
