"use client";

/**
 * The rules that open a HaloPSA ticket automatically for an alert type (made from an alert with "Open a ticket for alerts like this"). Each can be turned off; tickets already opened stay.
 */
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { ticketRulesApi, type TicketRule } from "@/lib/api";

export function TicketRules() {
  const [rules, setRules] = useState<TicketRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRules(await ticketRulesApi.list());
      setError(null);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not load the ticket rules");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function turnOff(rule: TicketRule) {
    setBusy(rule.id);
    try {
      await ticketRulesApi.turnOff(rule.id);
      setRules((rs) => (rs ?? []).filter((r) => r.id !== rule.id));
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not turn it off.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-3 p-6 pt-0" data-testid="ticket-rules">
      <h2 className="text-lg font-semibold">Automatic tickets</h2>
      <p className="text-sm text-gray-400">
        Alert types that get a HaloPSA ticket opened for them automatically (by CORE). Make one from an alert with &ldquo;Open a ticket for alerts like this&rdquo;. A rule covers alerts raised after it was made, at most one ticket per alert.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      {rules !== null && rules.length === 0 ? <p className="text-sm text-gray-500">No rules yet.</p> : null}
      <ul className="space-y-2">
        {(rules ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-gray-800 p-3 text-sm" data-testid="ticket-rule-row">
            <span className="min-w-0">
              <span className="block break-words text-gray-100">{r.title || "(no title)"}</span>
              <span className="text-xs text-gray-500">
                {r.scope === "all" ? "every client" : r.client_name ?? "one client"}
                {r.source ? ` · ${r.source}` : ""} · since {r.created_at.slice(0, 10)}
              </span>
            </span>
            <button type="button" disabled={busy === r.id} onClick={() => void turnOff(r)} className="text-xs text-gray-400 hover:text-red-300 disabled:opacity-50" aria-label={`Turn off the rule for ${r.title}`}>
              Turn off
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
