"use client";

/** Platform health: what CORE says about itself with each status report (GET /api/v1/health/core-heartbeat): the commit it runs, how long it has been up and how many feed passes it has made since it started. */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

export interface Heartbeat {
  reported: boolean;
  reported_at: string | null;
  commit: string | null;
  uptime_seconds: number | null;
  sweeps: number | null;
}

/** An uptime in words (pure): "3 d 4 h", "5 h 12 min", "7 min", or "under a minute". */
export function uptimeText(seconds: number): string {
  const m = Math.floor(seconds / 60);
  if (m < 1) return "under a minute";
  const d = Math.floor(m / 1440);
  const h = Math.floor((m % 1440) / 60);
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${m % 60} min`;
  return `${m} min`;
}

export function CoreHeartbeat() {
  const [beat, setBeat] = useState<Heartbeat | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch("/api/v1/health/core-heartbeat");
        if (res.ok && live) setBeat((await res.json()) as Heartbeat);
      } catch {
        /* the line is simply not shown */
      }
    })();
    return () => {
      live = false;
    };
  }, []);
  if (!beat) return null;
  if (!beat.reported) {
    return (
      <p className="text-xs text-gray-500" data-testid="core-heartbeat">
        CORE has not said what it is running lately (it reports every few minutes; an older CORE does not report this).
      </p>
    );
  }
  return (
    <p className="text-xs text-gray-400" data-testid="core-heartbeat">
      CORE runs commit <span className="font-mono text-gray-200">{beat.commit || "unknown"}</span>, has been up {uptimeText(beat.uptime_seconds ?? 0)} and has made {beat.sweeps ?? 0} feed pass{beat.sweeps === 1 ? "" : "es"} since it started.
    </p>
  );
}
