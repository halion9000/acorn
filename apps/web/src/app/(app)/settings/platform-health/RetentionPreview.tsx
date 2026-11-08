"use client";

/**
 * What the next retention sweep would delete, by kind of data, in every client. A dry run: it counts and deletes nothing. Only a platform administrator may ask; anyone else, or an older API, sees nothing here.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

export interface RetentionPreviewData {
  would_delete: Record<string, number>;
  failed: Record<string, string>;
  switched_on: boolean;
  note: string;
}

const NAMES: Record<string, string> = {
  copilot_conversations: "Leafy conversations",
  detection_suggestions: "Detection suggestions",
  response_actions: "Finished response actions",
  alerts: "Finished alerts with no case",
  posture_history: "Posture history",
};

export function RetentionPreview() {
  const [data, setData] = useState<RetentionPreviewData | null>(null);
  useEffect(() => {
    let live = true;
    authFetch("/api/v1/data-lifecycle/retention/preview")
      .then(async (res) => {
        if (!res.ok || !live) return;
        const body = (await res.json()) as Partial<RetentionPreviewData> | null;
        if (body && body.would_delete && typeof body.would_delete === "object" && typeof body.note === "string") setData(body as RetentionPreviewData);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  if (!data) return null;
  const rows = Object.entries(data.would_delete);
  return (
    <section className="mt-6 rounded border p-4" data-testid="retention-preview">
      <h2 className="text-sm font-semibold">What the next retention sweep would delete</h2>
      <p className="mt-1 text-xs text-gray-500">{data.note}</p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500" data-testid="retention-none">Nothing is due to be deleted.</p>
      ) : (
        <ul className="mt-2 text-sm">
          {rows.map(([k, n]) => (
            <li key={k} className="flex justify-between border-b py-1" data-testid={`retention-${k}`}>
              <span>{NAMES[k] ?? k.replace(/_/g, " ")}</span>
              <span className="tabular-nums">{n.toLocaleString("en-US")}</span>
            </li>
          ))}
        </ul>
      )}
      {Object.keys(data.failed).length > 0 ? <p className="mt-2 text-xs text-amber-600" data-testid="retention-failed">Could not be counted: {Object.keys(data.failed).map((k) => NAMES[k] ?? k).join(", ")}.</p> : null}
    </section>
  );
}
