"use client";

/**
 * Failed sign-ins in the lock window: how many, from how many places, and what is locked right now. Counts only: no typed address is named and client addresses have their last part hidden.
 * Shows nothing when the account may not read it or the server has no such view.
 */

import { useEffect, useState } from "react";
import { authFetch } from "@/lib/auth-session";

export interface LoginAbuse {
  window_minutes: number;
  failures: number;
  addresses_tried: number;
  clients: number;
  locked_addresses: number;
  locked_clients: number;
  busiest_clients: { client: string; failures: number }[];
}

export function isLoginAbuse(v: unknown): v is LoginAbuse {
  const o = v as Partial<LoginAbuse> | null;
  return !!o && typeof o.failures === "number" && typeof o.window_minutes === "number" && Array.isArray(o.busiest_clients);
}

export function LoginAbusePanel() {
  const [data, setData] = useState<LoginAbuse | null>(null);
  useEffect(() => {
    let live = true;
    authFetch("/api/v1/abuse/logins")
      .then((res) => (res.ok ? res.json() : null))
      .then((body: unknown) => {
        if (live && isLoginAbuse(body)) setData(body);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  if (!data) return null;
  const locked = data.locked_addresses + data.locked_clients;
  return (
    <div data-testid="login-abuse" className="text-sm text-gray-400">
      <p className={locked > 0 ? "text-amber-300" : undefined}>
        Failed sign-ins in the last {data.window_minutes} minutes: {data.failures} from {data.clients} place{data.clients === 1 ? "" : "s"} against {data.addresses_tried} address{data.addresses_tried === 1 ? "" : "es"}
        {locked > 0 ? `; locked now: ${data.locked_addresses} address${data.locked_addresses === 1 ? "" : "es"}, ${data.locked_clients} place${data.locked_clients === 1 ? "" : "s"}` : ""}.
      </p>
      {data.busiest_clients.length > 0 && (
        <p className="text-xs text-gray-500">
          Busiest: {data.busiest_clients.map((c) => `${c.client} (${c.failures})`).join(", ")}
        </p>
      )}
    </div>
  );
}
