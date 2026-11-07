"use client";

/**
 * Automatic installs: where Huntress, Field Effect or the approved ScreenConnect is missing on a Windows or Mac machine of a client that already uses it, CORE runs the install script for that machine's system.
 * A.C.O.R.N only asks; CORE decides per script whether to run at once or ask first, so until a script is switched to "run at once" in CORE every install waits for your approval there.
 */
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { toolInstallsApi, type ToolInstallRule, type ToolInstallScript } from "@/lib/api";

const TOOLS: { value: "huntress" | "fieldeffect" | "screenconnect"; label: string }[] = [
  { value: "huntress", label: "Huntress" },
  { value: "fieldeffect", label: "Field Effect" },
  { value: "screenconnect", label: "ScreenConnect" },
];

export function ToolInstalls() {
  const [rules, setRules] = useState<ToolInstallRule[] | null>(null);
  const [scripts, setScripts] = useState<ToolInstallScript[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tool, setTool] = useState<"huntress" | "fieldeffect" | "screenconnect">("huntress");
  const [windows, setWindows] = useState("");
  const [mac, setMac] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([toolInstallsApi.list(), toolInstallsApi.scripts()]);
      setRules(r);
      setScripts(s);
      setError(null);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not load the automatic installs");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const approval = (id: string) => (scripts.find((s) => String(s.id) === id)?.one_click ? "runs at once" : "asks for your approval in CORE first");

  async function make() {
    setBusy("new");
    try {
      await toolInstallsApi.make({ tool, scope: "all", windows_script_id: windows ? Number(windows) : undefined, mac_script_id: mac ? Number(mac) : undefined });
      setWindows("");
      setMac("");
      await load();
      toast.success("Automatic install made. It looks for gaps every few minutes.");
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not make the rule.");
    } finally {
      setBusy(null);
    }
  }

  async function turnOff(rule: ToolInstallRule) {
    setBusy(rule.id);
    try {
      await toolInstallsApi.turnOff(rule.id);
      setRules((rs) => (rs ?? []).filter((r) => r.id !== rule.id));
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not turn it off.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-3 p-6 pt-0" data-testid="tool-installs">
      <h2 className="text-lg font-semibold">Automatic installs</h2>
      <p className="text-sm text-gray-400">
        Install a tool where it is missing: on a Windows or Mac computer NinjaOne manages, of a client that already has the tool on at least one other machine (and not one marked as not using it). CORE runs the Windows or the Mac script. A machine is asked for at most once
        every two weeks, and until a script is switched to &ldquo;run at once&rdquo; in CORE, each install waits for your approval there.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      {rules !== null && rules.length === 0 ? <p className="text-sm text-gray-500">No automatic installs yet.</p> : null}
      <ul className="space-y-2">
        {(rules ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-gray-800 p-3 text-sm" data-testid="tool-install-row">
            <span className="min-w-0">
              <span className="block text-gray-100">{r.tool_name}</span>
              <span className="block text-xs text-gray-400">
                Windows: {r.windows_script ?? "none"} · Mac: {r.mac_script ?? "none"}
              </span>
              <span className="text-xs text-gray-500">
                {r.scope === "all" ? "every client" : r.client_name ?? "one client"} · since {r.created_at.slice(0, 10)}
              </span>
            </span>
            <button type="button" disabled={busy === r.id} onClick={() => void turnOff(r)} className="text-xs text-gray-400 hover:text-red-300 disabled:opacity-50" aria-label={`Turn off the automatic install of ${r.tool_name}`}>
              Turn off
            </button>
          </li>
        ))}
      </ul>
      <div className="space-y-2 rounded border border-gray-800 p-3 text-sm" data-testid="tool-install-form">
        <h3 className="font-medium text-gray-200">Add an automatic install (every client)</h3>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">Tool</span>
          <select value={tool} onChange={(e) => setTool(e.target.value as typeof tool)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Tool to install">
            {TOOLS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">Install script for Windows</span>
          <select value={windows} onChange={(e) => setWindows(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Install script for Windows">
            <option value="">None (leave Windows machines alone)</option>
            {scripts.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {windows ? <span className="text-xs text-gray-500">This script {approval(windows)}.</span> : null}
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">Install script for Mac</span>
          <select value={mac} onChange={(e) => setMac(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Install script for Mac">
            <option value="">None (leave Macs alone)</option>
            {scripts.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {mac ? <span className="text-xs text-gray-500">This script {approval(mac)}.</span> : null}
        </label>
        {scripts.length === 0 ? <p className="text-xs text-amber-300">CORE has not switched any script on, so there is nothing to choose. Switch the install scripts on in CORE first.</p> : null}
        <button type="button" disabled={busy === "new" || (!windows && !mac)} onClick={() => void make()} className="rounded bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-500 disabled:opacity-50">
          {busy === "new" ? "Adding…" : "Add"}
        </button>
      </div>
    </section>
  );
}
