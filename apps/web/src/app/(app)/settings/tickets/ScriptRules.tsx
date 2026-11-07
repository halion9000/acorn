"use client";

/**
 * The rules that run a script automatically for an alert type (made from an alert with "Auto-run script"), the Windows or Mac one by the machine. Each can be turned off; requests already sent stay.
 */
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { scriptRulesApi, type ScriptRule } from "@/lib/api";

export function ScriptRules() {
  const [rules, setRules] = useState<ScriptRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRules(await scriptRulesApi.list());
      setError(null);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not load the script rules");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function turnOff(rule: ScriptRule) {
    setBusy(rule.id);
    try {
      await scriptRulesApi.turnOff(rule.id);
      setRules((rs) => (rs ?? []).filter((r) => r.id !== rule.id));
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not turn it off.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-3 p-6 pt-0" data-testid="script-rules">
      <h2 className="text-lg font-semibold">Automatic scripts</h2>
      <p className="text-sm text-gray-400">
        Alert types that run a script on the machine automatically (by CORE), the Windows script on Windows and the Mac script on a Mac. Make one from an alert with &ldquo;Auto-run script&rdquo;. A rule covers alerts raised after it was made, one request per
        alert; whether a run starts at once or asks you first is set per script in CORE.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      {rules !== null && rules.length === 0 ? <p className="text-sm text-gray-500">No rules yet.</p> : null}
      <ul className="space-y-2">
        {(rules ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-gray-800 p-3 text-sm" data-testid="script-rule-row">
            <span className="min-w-0">
              <span className="block break-words text-gray-100">{r.title || "(no title)"}</span>
              <span className="block text-xs text-gray-400">
                Windows: {r.windows_script ?? "none"} · Mac: {r.mac_script ?? "none"}
                {r.requires_tool ? ` · only if the client uses ${r.requires_tool}` : ""}
              </span>
              <span className="text-xs text-gray-500">
                {r.scope === "all" ? "every client" : r.client_name ?? "one client"}
                {r.source ? ` · ${r.source}` : ""} · since {r.created_at.slice(0, 10)}
              </span>
            </span>
            <button type="button" disabled={busy === r.id} onClick={() => void turnOff(r)} className="text-xs text-gray-400 hover:text-red-300 disabled:opacity-50" aria-label={`Turn off the script rule for ${r.title}`}>
              Turn off
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
