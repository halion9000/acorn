"use client";

/**
 * Billing > Margin > "From HaloPSA": margin per client worked out from HaloPSA's recurring invoices (every line's quantity, unit price and unit cost), and the invoices still owed grouped by how late
 * they are. CORE reads HaloPSA and sends a snapshot about once a day; this shows the latest one and says when it arrived. Needs the finance permission (the API answers 403 without it, and the
 * panel above already says so, so this stays quiet).
 */
import { Fragment, useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

interface HaloMarginClient {
  client_id: string;
  client_name: string;
  recurring_invoices: number;
  revenue: string;
  costed_revenue: string;
  cost: string;
  margin: string;
  margin_percent: number | null;
  lines_without_cost: string[];
}
interface AgingInvoice {
  number: string;
  due: string | null;
  days_late: number;
  amount_due: string;
  bucket: string;
}
interface AgingClient {
  client_id: string;
  client_name: string;
  owed: string;
  buckets: Record<string, string>;
  invoices: AgingInvoice[];
}
export interface HaloFinance {
  received_at: string | null;
  margin: { clients: HaloMarginClient[]; totals: { revenue: string; cost: string; margin: string; margin_percent: number | null; costed_revenue: string } } | null;
  aging: { clients: AgingClient[]; totals: Record<string, string>; labels: Record<string, string> } | null;
}

const BUCKETS = ["not_due", "1_30", "31_60", "61_90", "over_90"] as const;
const pct = (v: number | null): string => (v === null ? "—" : `${v}%`);

/** "Updated 2026-11-13 14:02" or the reason nothing is shown yet. */
export function receivedText(at: string | null): string {
  if (!at) return "CORE has not sent HaloPSA's invoices yet. It sends them about once a day once HaloPSA is connected.";
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? "" : `From HaloPSA, as CORE last read it: ${d.toISOString().slice(0, 16).replace("T", " ")} UTC.`;
}

export function HaloFinancePanel() {
  const [data, setData] = useState<HaloFinance | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    authFetch("/api/v1/finance/halo")
      .then(async (res) => {
        if (!live || res.status === 403) return;
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        setData((await res.json()) as HaloFinance);
      })
      .catch((e) => live && setProblem(e instanceof Error ? e.message : "Could not load"));
    return () => {
      live = false;
    };
  }, []);

  if (problem) return <p className="text-sm text-amber-300">{problem}</p>;
  if (!data) return null;
  const { margin, aging } = data;
  return (
    <section className="space-y-4 border-t border-gray-800 pt-4" data-testid="halo-finance">
      <h3 className="text-sm font-semibold text-gray-100">From HaloPSA</h3>
      <p className="text-xs text-gray-500" data-testid="halo-finance-received">{receivedText(data.received_at)}</p>

      {margin && (
        <div className="space-y-1">
          <p className="text-xs text-gray-400">
            Margin per client from HaloPSA&apos;s recurring invoices, per invoice run (HaloPSA&apos;s own period is not turned into months). Only lines that have a cost in HaloPSA count towards margin; a line with no cost is named, never treated as free.
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th scope="col" className="py-1">Client</th>
                <th scope="col" className="py-1 text-right">Billed</th>
                <th scope="col" className="py-1 text-right">Cost</th>
                <th scope="col" className="py-1 text-right">Margin</th>
                <th scope="col" className="py-1 text-right">Margin %</th>
                <th scope="col" className="py-1">No cost in HaloPSA</th>
              </tr>
            </thead>
            <tbody>
              {margin.clients.map((c) => (
                <tr key={c.client_id} className="border-t border-gray-800" data-testid={`halo-margin-${c.client_name}`}>
                  <td className="py-1.5 text-gray-200">{c.client_name}</td>
                  <td className="py-1.5 text-right tabular-nums">{c.revenue}</td>
                  <td className="py-1.5 text-right tabular-nums">{c.cost}</td>
                  <td className="py-1.5 text-right tabular-nums">{c.margin}</td>
                  <td className="py-1.5 text-right tabular-nums">{pct(c.margin_percent)}</td>
                  <td className="py-1.5 text-xs text-gray-500">{c.lines_without_cost.join("; ")}</td>
                </tr>
              ))}
              <tr className="border-t border-gray-700 font-semibold text-gray-100" data-testid="halo-margin-total">
                <td className="py-1.5">All clients</td>
                <td className="py-1.5 text-right tabular-nums">{margin.totals.revenue}</td>
                <td className="py-1.5 text-right tabular-nums">{margin.totals.cost}</td>
                <td className="py-1.5 text-right tabular-nums">{margin.totals.margin}</td>
                <td className="py-1.5 text-right tabular-nums">{pct(margin.totals.margin_percent)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {aging && (
        <div className="space-y-1">
          <p className="text-xs text-gray-400">Invoices still owed, by how long past their due date. Press a client to see its invoices.</p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th scope="col" className="py-1">Client</th>
                {BUCKETS.map((b) => (
                  <th key={b} scope="col" className="py-1 text-right">{aging.labels[b] ?? b}</th>
                ))}
                <th scope="col" className="py-1 text-right">Owed</th>
              </tr>
            </thead>
            <tbody>
              {aging.clients.map((c) => (
                <Fragment key={c.client_id}>
                  <tr className="cursor-pointer border-t border-gray-800 hover:bg-gray-900/60" data-testid={`aging-${c.client_name}`} onClick={() => setOpen(open === c.client_id ? null : c.client_id)}>
                    <td className="py-1.5 text-gray-200">{c.client_name}</td>
                    {BUCKETS.map((b) => (
                      <td key={b} className={`py-1.5 text-right tabular-nums ${b !== "not_due" && Number(c.buckets[b]) > 0 ? "text-amber-300" : ""}`}>{c.buckets[b]}</td>
                    ))}
                    <td className="py-1.5 text-right font-medium tabular-nums">{c.owed}</td>
                  </tr>
                  {open === c.client_id && (
                    <tr className="bg-gray-900/40">
                      <td colSpan={BUCKETS.length + 2} className="px-3 py-2 text-xs text-gray-300">
                        <ul className="space-y-0.5" data-testid={`aging-invoices-${c.client_name}`}>
                          {c.invoices.map((i) => (
                            <li key={i.number}>
                              {i.number || "(no number)"} · {i.amount_due} · {i.due ? `due ${i.due}${i.days_late > 0 ? `, ${i.days_late} days late` : ""}` : "no due date"}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              <tr className="border-t border-gray-700 font-semibold text-gray-100" data-testid="aging-total">
                <td className="py-1.5">All clients</td>
                {BUCKETS.map((b) => (
                  <td key={b} className="py-1.5 text-right tabular-nums">{aging.totals[b]}</td>
                ))}
                <td className="py-1.5 text-right tabular-nums">{aging.totals.owed}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
