"use client";

/**
 * NIST CSF 2.0 for one client: each control, how the client stands today and the checks behind it, from what the tools already report. A control no check bears on says "No automated evidence": it needs a
 * person to show it and is never called met by default. Backed by GET /api/v1/nist-coverage/{client_id}. An older API without the route shows nothing.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

type Status = "met" | "partly" | "not_met" | "no_evidence";
interface Control {
  control_id: string;
  category: string;
  title: string;
  status: Status;
  checks: { key: string; status: string; evidence: string }[];
  met_since: string | null;
}
export interface NistCoverageData {
  controls: Control[];
  totals: Record<Status, number>;
}

/** A control met for this many days or more counts as evidenced: a person can show an auditor it has held, not just that it holds today. */
export const EVIDENCED_DAYS = 90;

/** Whole days a control has been met, from the date its checks last turned met; null when that date is unknown or in the future. */
export function daysMet(metSince: string | null, now: number = Date.now()): number | null {
  if (!metSince) return null;
  const t = Date.parse(metSince);
  if (!Number.isFinite(t) || t > now) return null;
  return Math.floor((now - t) / 86_400_000);
}

const LABEL: Record<Status, { text: string; className: string }> = {
  met: { text: "Met", className: "text-emerald-300" },
  partly: { text: "Partly", className: "text-amber-300" },
  not_met: { text: "Not met", className: "text-red-300" },
  no_evidence: { text: "No automated evidence", className: "text-gray-400" },
};

export function NistCoverage({ clientId }: { clientId: string }) {
  const [data, setData] = useState<NistCoverageData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    authFetch(`/api/v1/nist-coverage/${encodeURIComponent(clientId)}`)
      .then(async (res) => {
        if (!res.ok || !live) return;
        const body = (await res.json()) as Partial<NistCoverageData> | null;
        // An older or different answer (no controls or totals) shows nothing rather than a broken panel.
        if (body && Array.isArray(body.controls) && body.totals) setData(body as NistCoverageData);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [clientId]);
  if (!data) return null;
  const t = data.totals;
  const evidenced = data.controls.filter((c) => c.status === "met" && (daysMet(c.met_since) ?? 0) >= EVIDENCED_DAYS).length;
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="nist">
      <h3 className="text-sm font-semibold text-gray-100">NIST CSF 2.0</h3>
      <p className="mt-1 text-xs text-gray-400" data-testid="nist-totals">
        {t.met} met ({evidenced} for {EVIDENCED_DAYS}+ days) · {t.partly} partly · {t.not_met} not met · {t.no_evidence} need a person to show evidence. A control is met only when every check behind it is met.
      </p>
      <ul className="mt-3 divide-y divide-gray-800 text-sm">
        {data.controls.map((c) => (
          <li key={c.control_id} className="py-1.5" data-testid={`nist-${c.control_id}`}>
            <button type="button" className="flex w-full items-center justify-between gap-3 text-left" aria-expanded={open === c.control_id} onClick={() => setOpen(open === c.control_id ? null : c.control_id)}>
              <span className="text-gray-200">
                <span className="text-gray-500">{c.control_id}</span> {c.title}
              </span>
              <span className={LABEL[c.status].className}>
                {LABEL[c.status].text}
                {c.status === "met" && c.met_since ? ` since ${c.met_since.slice(0, 10)}${daysMet(c.met_since) !== null ? ` (${daysMet(c.met_since)} days)` : ""}` : ""}
              </span>
            </button>
            {open === c.control_id ? (
              c.checks.length === 0 ? (
                <p className="mt-1 pl-3 text-xs text-gray-500">No tool check bears on this control for this client. A person provides the evidence.</p>
              ) : (
                <ul className="mt-1 space-y-0.5 pl-3 text-xs text-gray-400">
                  {c.checks.map((k) => (
                    <li key={k.key}>
                      <span className={k.status === "met" ? "text-emerald-300" : k.status === "partly" ? "text-amber-300" : "text-red-300"}>{k.status.replace("_", " ")}</span> · {k.key.replace(/_/g, " ")}: {k.evidence}
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
