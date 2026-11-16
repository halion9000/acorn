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
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

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

  async function saveNote(rule: TicketRule) {
    if (draft.trim() === (rule.note ?? "")) {
      setEditing(null); // nothing changed: nothing to send
      return;
    }
    setBusy(rule.id);
    try {
      const saved = await ticketRulesApi.changeNote(rule.id, draft.trim());
      setRules((rs) => (rs ?? []).map((r) => (r.id === rule.id ? { ...r, note: saved.note ?? "" } : r)));
      setEditing(null);
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not save the note.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mx-auto max-w-2xl space-y-3 p-6 pt-0" data-testid="ticket-rules">
      <h2 className="text-lg font-semibold">Automatic tickets</h2>
      <p className="text-sm text-gray-400">
        Alert types that get a HaloPSA ticket opened for them automatically (by CORE). Make one from an alert with &ldquo;Open a ticket for alerts like this&rdquo;. A rule covers alerts raised after it was made, at most one ticket per alert. A rule can carry a note, which is written into every ticket it opens, so you can say what to do about that type of alert.
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
            <div className="w-full border-t border-gray-800 pt-2" data-testid="ticket-rule-note">
              {editing === r.id ? (
                <div className="space-y-2">
                  <textarea aria-label={`Note for the rule ${r.title}`} rows={3} maxLength={1000} value={draft} onChange={(e) => setDraft(e.target.value)} className="block w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100" />
                  <span className="flex gap-2">
                    <button type="button" disabled={busy === r.id} onClick={() => void saveNote(r)} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500 disabled:opacity-50">
                      Save note
                    </button>
                    <button type="button" onClick={() => setEditing(null)} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-300 hover:bg-gray-800">
                      Cancel
                    </button>
                  </span>
                </div>
              ) : (
                <span className="flex items-start justify-between gap-3">
                  <span className="min-w-0 whitespace-pre-wrap break-words text-xs text-gray-300">{r.note ? <><span className="text-gray-500">Note for the ticket: </span>{r.note}</> : <span className="text-gray-500">No note for the ticket.</span>}</span>
                  <button type="button" onClick={() => { setDraft(r.note ?? ""); setEditing(r.id); }} className="shrink-0 text-xs text-blue-300 hover:underline" aria-label={`Edit the note of the rule for ${r.title}`}>
                    {r.note ? "Edit note" : "Add note"}
                  </button>
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
