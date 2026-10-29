"use client";

/**
 * The history of one client-review question: when A.C.O.R.N's own reading of it changed, and what people typed, newest first.
 * Backed by GET /api/v1/client-review/{client}/history. Rendered as a button and, once pressed, a panel on its own row; hidden when printing.
 */
import { useState } from "react";

import { authFetch } from "@/lib/auth-session";

import type { Section } from "./AnswerEditor";

export interface HistoryEntry {
  at: string;
  source: "automatic" | "manual";
  status: string | null;
  detail: string | null;
  note: string | null;
  actor: string | null;
}

const STATUS_LABEL: Record<string, string> = {
  met: "Met",
  partly: "Partly",
  not_met: "Not met",
  unknown: "Not known",
  seen: "In use",
  not_seen: "None in use",
  needs_person: "Needs a person",
  not_applicable: "Not applicable",
};

/** One entry as a phrase: the status, then the evidence or typed answer, then who typed it. The Typed / Automatic mark beside it says which kind it is. Pure. */
export function entryText(e: HistoryEntry): string {
  const status = e.status ? (STATUS_LABEL[e.status] ?? e.status) : e.source === "manual" && !e.detail ? "Note only" : null;
  const head = [status, e.detail].filter(Boolean).join(" - ");
  return e.source === "manual" && e.actor ? `${head} (by ${e.actor})` : head;
}

async function load(clientId: string, section: Section, key: string): Promise<HistoryEntry[]> {
  const res = await authFetch(`/api/v1/client-review/${encodeURIComponent(clientId)}/history?section=${section}&key=${encodeURIComponent(key)}`);
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as HistoryEntry[];
}

export function QuestionHistory({ clientId, section, questionKey }: { clientId: string; section: Section; questionKey: string }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    if (open) return setOpen(false);
    setOpen(true);
    setRows(null);
    setError(null);
    try {
      setRows(await load(clientId, section, questionKey));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the history");
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        aria-label={`History of: ${questionKey}`}
        className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 print:hidden"
      >
        History
      </button>
      {open && (
        <div className="basis-full rounded border border-slate-800 bg-slate-950/60 p-2 text-xs print:hidden" data-testid="question-history">
          {error ? (
            <p role="alert" className="text-red-300">
              {error}
            </p>
          ) : rows === null ? (
            <p className="text-slate-500">Reading the history…</p>
          ) : rows.length === 0 ? (
            <p className="text-slate-500">Nothing recorded yet. A change to this answer, by A.C.O.R.N or a person, is kept from now on.</p>
          ) : (
            <ul className="space-y-1">
              {rows.map((r, i) => (
                <li key={`${r.at}-${i}`} className="flex gap-3">
                  <time dateTime={r.at} className="w-36 shrink-0 text-slate-500">
                    {new Date(r.at).toLocaleString()}
                  </time>
                  <span className="text-slate-300">
                    <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] ${r.source === "manual" ? "bg-sky-500/15 text-sky-300" : "bg-slate-700 text-slate-300"}`}>{r.source === "manual" ? "Typed" : "Automatic"}</span>
                    {entryText(r)}
                    {r.note ? <span className="block italic text-slate-400">Note: {r.note}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
