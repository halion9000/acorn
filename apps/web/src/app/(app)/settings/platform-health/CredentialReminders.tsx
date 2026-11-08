"use client";

/**
 * Reminders for stored credentials that have an end date: a name and a date each (never the credential itself). A date within 30 days shows as a warning at the top of this page.
 * Shown only to a platform administrator (the list is read with a permission others do not hold) and only when the server has the view.
 */

import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { authFetch } from "@/lib/auth-session";

export interface ReminderRow {
  name: string;
  expires_on: string;
  days_left?: number;
}

export function isReminderList(v: unknown): v is { entries: ReminderRow[] } {
  const o = v as { entries?: unknown } | null;
  return !!o && Array.isArray(o.entries) && o.entries.every((e) => !!e && typeof (e as ReminderRow).name === "string" && typeof (e as ReminderRow).expires_on === "string");
}

/** "in 12 days", "today", "expired 3 days ago". */
export function daysLeftText(days: number | undefined): string {
  if (days === undefined) return "";
  if (days === 0) return "today";
  if (days > 0) return `in ${days} day${days === 1 ? "" : "s"}`;
  return `expired ${-days} day${days === -1 ? "" : "s"} ago`;
}

export function CredentialReminders() {
  const [rows, setRows] = useState<ReminderRow[] | null>(null);
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    authFetch("/api/v1/platform/credential-expiries")
      .then((res) => (res.ok ? res.json() : null))
      .then((body: unknown) => {
        if (live && isReminderList(body)) setRows(body.entries);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  if (rows === null) return null;

  async function save(next: ReminderRow[]) {
    setBusy(true);
    try {
      const res = await authFetch("/api/v1/platform/credential-expiries", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: next.map((r) => ({ name: r.name, expires_on: r.expires_on })) }),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok || !isReminderList(body)) {
        const detail = (body as { detail?: unknown } | null)?.detail;
        toast.error(typeof detail === "string" ? detail : "Could not save that.");
        return;
      }
      setRows(body.entries);
      setName("");
      setDate("");
    } catch {
      toast.error("Could not save that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="credential-reminders" className="space-y-2 text-sm text-gray-300">
      <h3 className="text-sm font-medium text-gray-200">Credential reminders</h3>
      <p className="text-xs text-gray-500">A name and the day it stops working. Never type the credential itself. A date within 30 days shows as a warning at the top of this page.</p>
      {rows.length === 0 ? <p className="text-xs text-gray-500">Nothing is being tracked yet.</p> : null}
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.name} className="flex flex-wrap items-center gap-2" data-testid="reminder-row">
            <span className="text-gray-200">{r.name}</span>
            <span className="text-xs text-gray-400">
              {r.expires_on} {daysLeftText(r.days_left) ? `(${daysLeftText(r.days_left)})` : ""}
            </span>
            <button type="button" disabled={busy} onClick={() => void save(rows.filter((x) => x.name !== r.name))} className="text-xs text-gray-500 hover:text-red-300" aria-label={`Stop tracking ${r.name}`}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && date) void save([...rows, { name: name.trim(), expires_on: date }]);
        }}
      >
        <label className="text-xs text-gray-400">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Microsoft sign-in secret" className="ml-1 rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100" />
        </label>
        <label className="text-xs text-gray-400">
          Expires
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="ml-1 rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100" />
        </label>
        <button type="submit" disabled={busy || !name.trim() || !date} className="rounded border border-gray-600 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
          Add reminder
        </button>
      </form>
    </section>
  );
}
