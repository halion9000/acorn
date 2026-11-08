"use client";

/**
 * Platform health: is each internal service (fusion, connectors, agents, ...) answering its own probe right now?
 * Backed by GET /api/v1/health/services. Refreshes every 15 s; a service that does not answer is shown as down, never hidden.
 */
import { useCallback, useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { RetentionPreview } from "./RetentionPreview";
import { LoginAbusePanel } from "./LoginAbusePanel";
import { CredentialReminders } from "./CredentialReminders";
import { agoMinutes } from "@/lib/ago";

/** A restarted CORE takes about this long to finish its first round and report; a quiet spell shorter than the grace period is shown as a note, not a warning. */
export const RESTART_ROUND_MINUTES = 20;
export const RESTART_GRACE_MINUTES = 45;

/** True when CORE has been quiet long enough to be flagged but not so long that a restart no longer explains it (never when it has never reported). */
export function isRestarting(minutesAgo: number | null): boolean {
  return minutesAgo !== null && minutesAgo <= RESTART_GRACE_MINUTES;
}

interface ServiceRow {
  service: string;
  status: "up" | "down" | "off";
  latency_ms: number;
  detail: string;
}

interface SlowQueries {
  available: boolean;
  note: string | null;
  queries: { query: string; calls: number; typical_seconds: number; total_seconds: number }[];
}

interface DatabaseSecurity {
  slow_queries?: SlowQueries;
  enforced: boolean | null;
  reason: string;
  fix?: string;
  pool?: {
    known: boolean;
    in_use?: number;
    limit?: number;
    percent?: number;
    near_limit?: boolean;
    peak_last_hour?: { samples: number; peak_in_use?: number; peak_limit?: number; peak_percent?: number; peak_minutes_ago?: number };
  };
}

interface DeviceFeed {
  vendor: string;
  devices: number;
  last_synced: string | null;
  minutes_ago: number | null;
  stalled: boolean;
}

/** How long ago, in plain words. */
export function agoLabel(minutes: number | null): string {
  return agoMinutes(minutes);
}

interface SlowRoute {
  route: string;
  calls: number;
  total_seconds: number;
  typical_seconds: number;
  p95_seconds: number;
  worst_seconds: number;
}

interface WorkerRow {
  name: string;
  interval_seconds: number;
  seconds_since_pass: number | null;
  passes: number;
  last_error: string | null;
  status: "ok" | "failing" | "waiting" | "late";
}

export interface RateLimitTally {
  mode: 'off' | 'log' | 'enforce';
  per_minute: number;
  checked: number;
  over_limit: number;
  callers_over_limit: number;
}

/** What the API-wide request limit has done since the API started, in plain words: in log mode it says how many requests it WOULD have refused, so the limit can be judged before it is switched on. */
export function rateLimitLabel(r: RateLimitTally): string {
  if (r.mode === 'off') return 'Request limit: off.';
  const over = r.over_limit === 0 ? 'no caller went over' : `${r.over_limit.toLocaleString()} request${r.over_limit === 1 ? '' : 's'} from ${r.callers_over_limit} caller${r.callers_over_limit === 1 ? '' : 's'} went over`;
  return r.mode === 'log'
    ? `Request limit: logging only (${r.per_minute} a minute per caller); nothing is refused. Since the API started, ${over}.`
    : `Request limit: ${r.per_minute} a minute per caller, enforced. Since the API started, ${over}.`;
}

/** "Running version abc1234, up 2 h": which commit the API is, and for how long. Says plainly when it does not know the commit. */
export function runningLabel(v: { commit: string | null; up_seconds: number }): string {
  const s = v.up_seconds;
  const up = s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172_800 ? `${(s / 3600).toFixed(1).replace(/\.0$/, "")} h` : `${Math.round(s / 86_400)} days`;
  return v.commit ? `Running version ${v.commit}, up ${up}.` : `Running version unknown (started by hand, not by the update), up ${up}.`;
}

/** "148 database updates applied, newest 148_x.sql (2 Nov)": says plainly when the database could not be read. */
export function migrationsLabel(m: { applied: number; newest: string | null; applied_at: string | null } | null | undefined): string {
  if (!m) return "Database updates: could not be read.";
  if (!m.newest) return "No database updates are recorded yet.";
  const when = m.applied_at ? new Date(m.applied_at) : null;
  const day = when && !Number.isNaN(when.getTime()) ? ` (${when.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })})` : "";
  return `${m.applied} database updates applied, newest ${m.newest}${day}.`;
}

/** What a worker's status reads as on the page, in plain words. */
export function workerLabel(w: Pick<WorkerRow, "status" | "seconds_since_pass" | "last_error">): string {
  if (w.status === "late") return w.seconds_since_pass === null ? "never ran: something is wrong" : `quiet for ${Math.floor(w.seconds_since_pass / 60)} min: something is wrong`;
  if (w.status === "failing") return `last pass failed${w.last_error ? ` (${w.last_error})` : ""}`;
  if (w.status === "waiting") return "waiting for its first turn";
  return "running";
}

interface FeedRoute {
  route: string;
  last_ok_minutes_ago: number | null;
  ok: number;
  errors: number;
  last_error_minutes_ago: number | null;
  last_error_status: number | null;
}

interface Snapshot {
  overall: "ok" | "degraded";
  down: string[];
  services: ServiceRow[];
  device_feeds?: DeviceFeed[];
  signins?: { last_24h: number; scored_last_24h: number; unscored: number; users_last_24h: number; newest_received: string | null } | null;
  core_feed?: { sources: number; last_report: string | null; minutes_ago: number | null; silent: boolean } | null;
  warnings?: { key: string; level: "error" | "warn"; text: string }[];
  database?: DatabaseSecurity;
  feed_routes?: { since_minutes_ago: number; routes: FeedRoute[] };
  migrations?: { applied: number; newest: string | null; applied_at: string | null } | null;
  runtime?: { version?: { commit: string | null; up_seconds: number }; loop?: { samples: number; max_seconds?: number; typical_seconds?: number; window_seconds: number }; slow_routes?: SlowRoute[]; workers?: WorkerRow[]; rate_limit?: RateLimitTally };
  generated_at: string;
}

export function PlatformHealth() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/health/services");
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setSnapshot((await res.json()) as Snapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load platform health");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <h1 className="text-xl font-semibold text-gray-100">Platform health</h1>
      {error && (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!snapshot && !error && <p className="text-sm text-gray-500">Checking the services...</p>}
      {snapshot && (
        <>
          <p className={snapshot.overall === "ok" ? "text-emerald-700" : "text-red-700"} data-testid="overall">
            {snapshot.overall === "ok" ? "Every service is answering." : `Not answering: ${snapshot.down.join(", ")}`}
          </p>
          <LoginAbusePanel />
          <CredentialReminders />
          {snapshot.database && snapshot.database.enforced !== true && (
            <p role="note" data-testid="row-security" className="rounded border border-yellow-500/40 bg-yellow-500/10 p-3 text-sm text-yellow-200">
              {snapshot.database.enforced === false ? 'Tenant isolation in the database is not being enforced: ' : 'Could not check tenant isolation in the database: '}
              {snapshot.database.reason}.{snapshot.database.fix ? ` To fix: ${snapshot.database.fix}.` : ''}
            </p>
          )}
          {snapshot.database?.slow_queries && (
            <div data-testid="slow-queries">
              {!snapshot.database.slow_queries.available ? (
                <p className="text-sm text-gray-500">{snapshot.database.slow_queries.note}</p>
              ) : snapshot.database.slow_queries.queries.length === 0 ? (
                <p className="text-sm text-gray-500">The database has not run any statement often enough yet to list the slow ones.</p>
              ) : (
                <table className="w-full text-left text-xs text-gray-300">
                  <caption className="pb-1 text-left text-sm text-gray-400">Database statements with the longest typical time (values are replaced by $1, $2)</caption>
                  <thead>
                    <tr className="text-gray-500">
                      <th scope="col">Statement</th>
                      <th scope="col">Calls</th>
                      <th scope="col">Typical (s)</th>
                      <th scope="col">Total (s)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.database.slow_queries.queries.map((q) => (
                      <tr key={q.query}>
                        <td className="break-all font-mono">{q.query}</td>
                        <td>{q.calls}</td>
                        <td>{q.typical_seconds}</td>
                        <td>{q.total_seconds}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {snapshot.database?.pool?.peak_last_hour && snapshot.database.pool.peak_last_hour.samples > 0 && (
            <p data-testid="pool-peak" className={`text-sm ${(snapshot.database.pool.peak_last_hour.peak_percent ?? 0) >= 80 ? "text-red-300" : "text-gray-400"}`}>
              Database connections: busiest in the last hour was {snapshot.database.pool.peak_last_hour.peak_percent}% ({snapshot.database.pool.peak_last_hour.peak_in_use} of {snapshot.database.pool.peak_last_hour.peak_limit}),{" "}
              {agoLabel(snapshot.database.pool.peak_last_hour.peak_minutes_ago ?? null)}.
            </p>
          )}
          {snapshot.database?.pool?.known && snapshot.database.pool.near_limit && (
            <p role="note" data-testid="pool-warning" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
              The database connection pool is {snapshot.database.pool.percent}% full ({snapshot.database.pool.in_use} of {snapshot.database.pool.limit} in use). When it is full, pages start failing with 500
              errors until requests finish.
            </p>
          )}
          {snapshot.migrations !== undefined && (
            <p data-testid="migrations-line" className="text-sm text-gray-400">
              {migrationsLabel(snapshot.migrations)}
            </p>
          )}
          {snapshot.runtime?.version && (
            <p data-testid="running-version" className="text-sm text-gray-400">
              {runningLabel(snapshot.runtime.version)}
            </p>
          )}
          {snapshot.runtime?.rate_limit && (
            <p data-testid="rate-limit" className="text-sm text-gray-400">
              {rateLimitLabel(snapshot.runtime.rate_limit)}
            </p>
          )}
          {snapshot.runtime?.loop && snapshot.runtime.loop.samples > 0 && (
            <p data-testid="loop-lag" className="text-sm text-gray-400">
              The API&apos;s wake-up delay over the last {Math.round(snapshot.runtime.loop.window_seconds / 60)} minutes: typically {snapshot.runtime.loop.typical_seconds} s, worst {snapshot.runtime.loop.max_seconds} s.
            </p>
          )}
          {(snapshot.runtime?.slow_routes ?? []).length > 0 && (
            <table data-testid="slow-routes" className="w-full text-left text-xs text-gray-300">
              <caption className="pb-1 text-left text-sm text-gray-400">Routes that have taken the most time since the API started</caption>
              <thead>
                <tr className="text-gray-500">
                  <th scope="col">Route</th>
                  <th scope="col">Calls</th>
                  <th scope="col">Total (s)</th>
                  <th scope="col">Typical (s)</th>
                  <th scope="col">Slowest 5% (s)</th>
                  <th scope="col">Worst (s)</th>
                </tr>
              </thead>
              <tbody>
                {(snapshot.runtime?.slow_routes ?? []).map((r) => (
                  <tr key={r.route}>
                    <td className="font-mono">{r.route}</td>
                    <td>{r.calls}</td>
                    <td>{r.total_seconds}</td>
                    <td>{r.typical_seconds}</td>
                    <td>{r.p95_seconds}</td>
                    <td>{r.worst_seconds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(snapshot.runtime?.workers ?? []).length > 0 && (
            <table data-testid="workers" className="w-full text-left text-xs text-gray-300">
              <caption className="pb-1 text-left text-sm text-gray-400">Background work since the API started (the worst is first)</caption>
              <thead>
                <tr className="text-gray-500">
                  <th scope="col">Worker</th>
                  <th scope="col">Runs every</th>
                  <th scope="col">Last pass</th>
                  <th scope="col">Passes</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {(snapshot.runtime?.workers ?? []).map((w) => (
                  <tr key={w.name}>
                    <td className="font-mono">{w.name}</td>
                    <td>{Math.round(w.interval_seconds / 60) || 1} min</td>
                    <td>{w.seconds_since_pass === null ? "none yet" : `${Math.floor(w.seconds_since_pass / 60)} min ago`}</td>
                    <td>{w.passes}</td>
                    <td data-testid={`worker-${w.name}`} className={w.status === "ok" || w.status === "waiting" ? "text-gray-300" : w.status === "failing" ? "text-amber-300" : "text-red-300"}>
                      {workerLabel(w)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(snapshot.feed_routes?.routes ?? []).length > 0 && (
            <table data-testid="feed-routes" className="w-full text-left text-xs text-gray-300">
              <caption className="pb-1 text-left text-sm text-gray-400">
                When CORE last reported on each route (since the API started {agoLabel(snapshot.feed_routes?.since_minutes_ago ?? 0)}); the quietest is first
              </caption>
              <thead>
                <tr className="text-gray-500">
                  <th scope="col">Route</th>
                  <th scope="col">Last accepted</th>
                  <th scope="col">Accepted</th>
                  <th scope="col">Refused</th>
                  <th scope="col">Last refusal</th>
                </tr>
              </thead>
              <tbody>
                {(snapshot.feed_routes?.routes ?? []).map((r) => (
                  <tr key={r.route}>
                    <td className="font-mono">{r.route}</td>
                    <td>{r.last_ok_minutes_ago === null ? "never" : agoLabel(r.last_ok_minutes_ago)}</td>
                    <td>{r.ok}</td>
                    <td>{r.errors}</td>
                    <td>{r.last_error_minutes_ago === null ? "none" : `${agoLabel(r.last_error_minutes_ago)} (${r.last_error_status})`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(snapshot.warnings ?? []).filter((w) => w.key !== "services" && w.key !== "core").length > 0 && (
            <ul data-testid="warnings" className="space-y-1 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
              {(snapshot.warnings ?? [])
                .filter((w) => w.key !== "services" && w.key !== "core")
                .map((w) => (
                  <li key={w.key} className={w.level === "error" ? "text-red-300" : undefined}>
                    {w.text}
                  </li>
                ))}
            </ul>
          )}
          {snapshot.core_feed?.silent && isRestarting(snapshot.core_feed.minutes_ago) && (
            <p role="note" data-testid="core-restarting" className="rounded border border-gray-600 bg-gray-800/60 p-3 text-sm text-gray-300">
              CORE has been quiet for {snapshot.core_feed.minutes_ago} minutes. If it was just restarted, that is normal: its first round after a start can take about {RESTART_ROUND_MINUTES} minutes. If it is still silent after{" "}
              {RESTART_GRACE_MINUTES} minutes, check that CORE is running and can reach A.C.O.R.N.
            </p>
          )}
          {snapshot.core_feed?.silent && !isRestarting(snapshot.core_feed.minutes_ago) && (
            <p role="note" data-testid="core-silent" className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
              CORE has not reported to A.C.O.R.N {snapshot.core_feed.minutes_ago === null ? "yet" : `since ${agoLabel(snapshot.core_feed.minutes_ago).replace(" ago", "")} ago`}. While it is silent, no new alerts, devices or
              links arrive from Huntress, Petra, NinjaOne and the other tools. Check that CORE is running and can reach A.C.O.R.N.
            </p>
          )}
          {snapshot.signins && (
            <p data-testid="signins-line" className="text-sm text-gray-300">
              Sign-ins collected through CORE: {snapshot.signins.last_24h.toLocaleString()} in the last 24 hours from {snapshot.signins.users_last_24h.toLocaleString()} people,{" "}
              {snapshot.signins.scored_last_24h.toLocaleString()} scored for unusual behaviour
              {snapshot.signins.unscored > 0 ? `, ${snapshot.signins.unscored.toLocaleString()} waiting to be scored (is the behaviour service up?)` : ""}.
            </p>
          )}
          {snapshot.device_feeds && snapshot.device_feeds.length > 0 && (
            <section aria-label="Device feeds" data-testid="device-feeds">
              <h2 className="mb-1 text-sm font-medium text-gray-300">Device feeds</h2>
              <ul className="space-y-1 text-sm">
                {snapshot.device_feeds.map((f) => (
                  <li key={f.vendor} className={f.stalled ? "text-red-300" : "text-gray-300"}>
                    <span className="font-medium">{f.vendor}</span>: {f.devices.toLocaleString()} devices, last synced {agoLabel(f.minutes_ago)}
                    {f.stalled ? " (nothing for hours: is CORE running, and is this tool's connector working?)" : ""}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-gray-500">
                <th className="py-2">Service</th>
                <th>Status</th>
                <th>Answered in</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.services.map((s) => (
                <tr key={s.service} className="border-b">
                  <td className="py-2 font-medium">{s.service}</td>
                  <td className={s.status === "up" ? "text-emerald-700" : s.status === "off" ? "text-gray-500" : "text-red-700"}>{s.status === "off" ? "off (not switched on)" : s.status}</td>
                  <td>{s.latency_ms} ms</td>
                  <td className="text-gray-500">{s.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <RetentionPreview />
    </div>
  );
}
