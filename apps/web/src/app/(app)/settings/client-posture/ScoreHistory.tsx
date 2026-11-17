"use client";

/** The client's check score over time as a line (0 to 100), with a choice of 30, 90 or 365 days and how far it moved. Reads GET /api/v1/client-posture/{client}/score-history; says so when there is no history yet. */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { CHART_H, CHART_W, PAD, changeText, chartPoints, linePath, yOf, type ScoreDay } from "./scoreChart";

const RANGES = [30, 90, 365] as const;

export function ScoreHistory({ clientId }: { clientId: string }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(90);
  const [rows, setRows] = useState<ScoreDay[] | null>(null);
  useEffect(() => {
    let live = true;
    setRows(null);
    authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/score-history?days=${days}`)
      .then(async (res) => (res.ok ? ((await res.json()) as { rows?: ScoreDay[] }).rows ?? [] : []))
      .catch(() => [] as ScoreDay[])
      .then((r) => live && setRows(r));
    return () => {
      live = false;
    };
  }, [clientId, days]);
  const points = rows ? chartPoints(rows) : [];
  return (
    <section data-testid="score-history" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm uppercase text-gray-500">Score over time</h3>
        <div className="flex gap-1 print:hidden" role="group" aria-label="Score history period">
          {RANGES.map((d) => (
            <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)} className={`rounded border px-2 py-0.5 text-xs ${days === d ? "border-sky-500 text-sky-200" : "border-gray-700 text-gray-400"}`}>
              {d === 365 ? "1 year" : `${d} days`}
            </button>
          ))}
        </div>
      </div>
      {rows === null ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : points.length === 0 ? (
        <p className="text-sm text-gray-400" data-testid="score-history-empty">No score has been recorded for this client in that period yet.</p>
      ) : (
        <>
          <p className="text-sm text-gray-300" data-testid="score-history-change">
            {points[points.length - 1]!.score}% now{points.length > 1 ? `, ${changeText(points)} since ${points[0]!.day}` : ""}.
          </p>
          <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label="The client's score over time" className="w-full max-w-2xl">
            {[0, 25, 50, 75, 100].map((s) => (
              <g key={s}>
                <line x1={PAD.left} x2={CHART_W - PAD.right} y1={yOf(s)} y2={yOf(s)} stroke="#374151" strokeWidth={0.6} />
                <text x={PAD.left - 5} y={yOf(s) + 3} textAnchor="end" fontSize={9} fill="#6b7280">{s}</text>
              </g>
            ))}
            <path d={linePath(points)} fill="none" stroke="#38bdf8" strokeWidth={2} strokeLinejoin="round" />
            {points.map((p) => (
              <circle key={p.day} cx={p.x} cy={p.y} r={points.length > 60 ? 1.2 : 2.5} fill="#38bdf8">
                <title>{`${p.day}: ${p.score}%`}</title>
              </circle>
            ))}
            <text x={PAD.left} y={CHART_H - 6} fontSize={9} fill="#6b7280">{points[0]!.day}</text>
            <text x={CHART_W - PAD.right} y={CHART_H - 6} textAnchor="end" fontSize={9} fill="#6b7280">{points[points.length - 1]!.day}</text>
          </svg>
        </>
      )}
    </section>
  );
}
