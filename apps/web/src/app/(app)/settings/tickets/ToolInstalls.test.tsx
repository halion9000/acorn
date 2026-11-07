import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({ list: vi.fn(), scripts: vi.fn(), make: vi.fn(), turnOff: vi.fn(), children: vi.fn(), toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/api", () => ({ toolInstallsApi: { list: api.list, scripts: api.scripts, make: api.make, turnOff: api.turnOff }, msspApi: { listChildren: api.children } }));
vi.mock("react-hot-toast", () => ({ default: api.toast }));

import { ToolInstalls } from "./ToolInstalls";

const scripts = [
  { id: 201, name: "Install Huntress (Windows)", one_click: false },
  { id: 202, name: "Install Huntress (Mac)", one_click: true },
];
const rule = (over: Record<string, unknown> = {}) => ({ id: "r1", tool: "huntress", tool_name: "Huntress", scope: "all", client_name: null, windows_script: "Install Huntress (Windows)", mac_script: null, created_at: "2026-11-07T12:00:00Z", active: true, ...over });

beforeEach(() => {
  api.list.mockReset().mockResolvedValue([]);
  api.scripts.mockReset().mockResolvedValue(scripts);
  api.make.mockReset().mockResolvedValue(rule());
  api.turnOff.mockReset().mockResolvedValue({});
  api.children.mockReset().mockResolvedValue([{ id: "c1", name: "Acme", mssp_role: "client" }]);
  api.toast.error.mockReset();
  api.toast.success.mockReset();
});

describe("ToolInstalls", () => {
  it("lists each rule with its scripts per system and who it covers, and says when there are none or the list cannot be read", async () => {
    api.list.mockResolvedValueOnce([rule()]);
    const a = render(<ToolInstalls />);
    expect(await screen.findByTestId("tool-install-row")).toHaveTextContent("Windows: Install Huntress (Windows) · Mac: none");
    a.unmount();
    render(<ToolInstalls />);
    expect(await screen.findByText("No automatic installs yet.")).toBeInTheDocument();
  });

  it("shows the reason when the list cannot be read", async () => {
    api.list.mockRejectedValueOnce(new Error("The API answered 500"));
    render(<ToolInstalls />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API answered 500");
  });

  it("cannot add until a script is chosen, says whether CORE asks first for each, and sends the choice", async () => {
    const user = userEvent.setup();
    render(<ToolInstalls />);
    const add = await screen.findByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Install script for Windows" }), "201");
    expect(screen.getByText(/asks for your approval in CORE first/)).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Install script for Mac" }), "202");
    expect(screen.getByText(/runs at once/)).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Tool to install" }), "fieldeffect");
    await user.click(add);
    await waitFor(() => expect(api.make).toHaveBeenCalledWith({ tool: "fieldeffect", scope: "all", windows_script_id: 201, mac_script_id: 202 }));
    expect(api.toast.success).toHaveBeenCalled();
  });

  it("makes a rule for one chosen client, and for every client when none is chosen", async () => {
    const user = userEvent.setup();
    render(<ToolInstalls />);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Install script for Windows" }), "201");
    await user.selectOptions(screen.getByRole("combobox", { name: "Client for the install" }), "c1");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith({ tool: "huntress", scope: "client", client_id: "c1", windows_script_id: 201, mac_script_id: undefined }));
  });

  it("can make a Huntress rule that pushes through Addigy with no script chosen, and offers that for no other tool", async () => {
    const user = userEvent.setup();
    render(<ToolInstalls />);
    const add = await screen.findByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Also push through Addigy" }));
    expect(add).toBeEnabled();
    await user.click(add);
    await waitFor(() => expect(api.make).toHaveBeenCalledWith({ tool: "huntress", via_addigy: true, scope: "all", windows_script_id: undefined, mac_script_id: undefined }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Tool to install" }), "fieldeffect");
    expect(screen.queryByRole("checkbox", { name: "Also push through Addigy" })).not.toBeInTheDocument();
  });

  it("shows the refusal, and turns a rule off and removes it", async () => {
    api.list.mockResolvedValue([rule()]);
    api.make.mockRejectedValueOnce(new Error("There is already an automatic install of this tool for that place."));
    const user = userEvent.setup();
    render(<ToolInstalls />);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Install script for Windows" }), "201");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith("There is already an automatic install of this tool for that place."));
    await user.click(screen.getByRole("button", { name: "Turn off the automatic install of Huntress" }));
    await waitFor(() => expect(screen.queryByTestId("tool-install-row")).not.toBeInTheDocument());
    expect(api.turnOff).toHaveBeenCalledWith("r1");
  });
});
