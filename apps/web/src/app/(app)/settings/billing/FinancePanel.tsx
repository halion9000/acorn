"use client";

/**
 * Billing > "Margin": what each invoice line sells and costs per unit (typed in here), and the estimated revenue, cost and margin per client from the quantities each client is billed for.
 * Needs the finance permission, which is not held by anyone who only holds the licence-count permissions; without it the API answers 403 and this says so instead of showing money.
 */
import { useCallback, useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { HaloFinancePanel } from "./HaloFinancePanel";

interface Price {
  invoice_item: string;
  unit_price: string;
  unit_cost: string;
}
interface Prices {
  prices: Price[];
  billed_items: string[];
}
interface MarginClient {
  client_id: string;
  client_name: string;
  revenue: string;
  cost: string;
  margin: string;
  margin_percent: number | null;
  unpriced_items: string[];
}
interface MarginOut {
  clients: MarginClient[];
  totals: { revenue: string; cost: string; margin: string; margin_percent: number | null };
  priced_items: number;
  note: string;
}

const input = "rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100";
const ghost = "rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50";
const pct = (v: number | null): string => (v === null ? "—" : `${v}%`);

export function FinancePanel() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [prices, setPrices] = useState<Prices | null>(null);
  const [margin, setMargin] = useState<MarginOut | null>(null);
  const [item, setItem] = useState("");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, m] = await Promise.all([authFetch("/api/v1/finance/prices"), authFetch("/api/v1/finance/margin")]);
      if (p.status === 403 || m.status === 403) {
        setDenied(true);
        return;
      }
      if (!p.ok || !m.ok) throw new Error(`The API answered ${p.ok ? m.status : p.status}`);
      setPrices((await p.json()) as Prices);
      setMargin((await m.json()) as MarginOut);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not load");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const res = await authFetch("/api/v1/finance/prices", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ invoice_item: item, unit_price: price, unit_cost: cost }),
      });
      if (res.status === 403) throw new Error("You can see prices but not change them.");
      if (!res.ok) throw new Error(`The price was not saved (${res.status}).`);
      setItem("");
      setPrice("");
      setCost("");
      await load();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  if (denied) return <p className="text-sm text-gray-400" data-testid="finance-denied">Prices and margins are only shown to roles that hold the finance permission. Ask a workspace owner to add it to your role.</p>;
  if (problem && !prices) return <p className="text-sm text-amber-300">{problem}</p>;
  if (!prices || !margin) return <p className="text-sm text-gray-400">Loading…</p>;
  const unpricedBilled = prices.billed_items.filter((i) => !prices.prices.some((p) => p.invoice_item === i));

  return (
    <div className="space-y-4" data-testid="finance">
      <p className="text-sm text-gray-400">{margin.note}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-400">
          Invoice line
          <input list="finance-items" className={`${input} mt-1 block w-72`} value={item} onChange={(e) => setItem(e.target.value)} />
        </label>
        <datalist id="finance-items">
          {unpricedBilled.map((i) => (
            <option key={i} value={i} />
          ))}
        </datalist>
        <label className="text-xs text-gray-400">
          Price per unit
          <input inputMode="decimal" className={`${input} mt-1 block w-28`} value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          Cost per unit
          <input inputMode="decimal" className={`${input} mt-1 block w-28`} value={cost} onChange={(e) => setCost(e.target.value)} />
        </label>
        <button type="button" className={ghost} disabled={busy || !item.trim() || price === "" || cost === ""} onClick={() => void save()}>Save price</button>
      </div>
      {problem ? <p className="text-sm text-amber-300" data-testid="finance-problem">{problem}</p> : null}
      {unpricedBilled.length > 0 ? <p className="text-xs text-gray-500" data-testid="finance-unpriced">Billed but not priced yet: {unpricedBilled.join("; ")}.</p> : null}
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-gray-500">
          <tr>
            <th scope="col" className="py-1">Client</th>
            <th scope="col" className="py-1 text-right">Revenue</th>
            <th scope="col" className="py-1 text-right">Cost</th>
            <th scope="col" className="py-1 text-right">Margin</th>
            <th scope="col" className="py-1 text-right">Margin %</th>
            <th scope="col" className="py-1">Not priced</th>
          </tr>
        </thead>
        <tbody>
          {margin.clients.map((c) => (
            <tr key={c.client_id} className="border-t border-gray-800" data-testid={`margin-${c.client_name}`}>
              <td className="py-1.5 text-gray-200">{c.client_name}</td>
              <td className="py-1.5 text-right tabular-nums">{c.revenue}</td>
              <td className="py-1.5 text-right tabular-nums">{c.cost}</td>
              <td className="py-1.5 text-right tabular-nums">{c.margin}</td>
              <td className="py-1.5 text-right tabular-nums">{pct(c.margin_percent)}</td>
              <td className="py-1.5 text-xs text-gray-500">{c.unpriced_items.join("; ")}</td>
            </tr>
          ))}
          <tr className="border-t border-gray-700 font-semibold text-gray-100" data-testid="margin-total">
            <td className="py-1.5">All clients</td>
            <td className="py-1.5 text-right tabular-nums">{margin.totals.revenue}</td>
            <td className="py-1.5 text-right tabular-nums">{margin.totals.cost}</td>
            <td className="py-1.5 text-right tabular-nums">{margin.totals.margin}</td>
            <td className="py-1.5 text-right tabular-nums">{pct(margin.totals.margin_percent)}</td>
            <td />
          </tr>
        </tbody>
      </table>
      <HaloFinancePanel />
    </div>
  );
}
