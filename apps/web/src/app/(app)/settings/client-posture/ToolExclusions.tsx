"use client";

/**
 * "Tools this client does not use": tick a tool and it is no longer reported as missing for this client, on Devices, here, in the fleet boards and the score, and its checks raise no alerts.
 * Backed by GET and PUT /api/v1/client-posture/{client_id}/tool-exclusions.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { vendorLabel } from "@/components/mssp/ClientMapping";

/** The tools people ask to switch off most, first; the rest follow in the order the API sends them. */
const FIRST = ["huntress", "screenconnect", "addigy", "fieldeffect"];

export function orderedChoices(choices: string[]): string[] {
  return [...FIRST.filter((c) => choices.includes(c)), ...choices.filter((c) => !FIRST.includes(c))];
}

/** The list after one tick: the tool added or removed, never twice. */
export function toggled(current: string[], tool: string, on: boolean): string[] {
  const rest = current.filter((t) => t !== tool);
  return on ? [...rest, tool] : rest;
}

export function ToolExclusions({ clientId, onLoaded, onChanged }: { clientId: string; onLoaded: (excluded: string[]) => void; onChanged: (excluded: string[]) => void }) {
  const [choices, setChoices] = useState<string[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoaded(false);
    authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/tool-exclusions`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as { tools: string[]; choices: string[] };
        if (!live) return;
        const tools = Array.isArray(body.tools) ? body.tools : [];
        setChoices(orderedChoices(Array.isArray(body.choices) ? body.choices : []));
        setExcluded(tools);
        setLoaded(true);
        setError(null);
        onLoaded(tools);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Could not load the tool choices");
      });
    return () => {
      live = false;
    };
    // The parent's callbacks are only told what was read or saved; they must not re-trigger the read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  const change = async (tool: string, on: boolean) => {
    const next = toggled(excluded, tool, on);
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/tool-exclusions`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tools: next }),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(res.status === 403 ? "You need permission to manage clients to change this." : (detail?.detail ?? `The API answered ${res.status}`));
      }
      const body = (await res.json()) as { tools: string[] };
      setExcluded(body.tools);
      onChanged(body.tools);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  if (!loaded && !error) return null;
  return (
    <section aria-label="Tools this client does not use" className="print:hidden" data-testid="tool-exclusions">
      <h3 className="mb-1 text-sm uppercase text-slate-500">Tools this client does not use</h3>
      <p className="mb-2 text-xs text-slate-500">
        A ticked tool is never reported as missing for this client: not on the Devices page, not here, not in the fleet boards or the score, and its checks raise no alerts.
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {choices.map((tool) => (
          <li key={tool}>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={excluded.includes(tool)} disabled={saving} onChange={(e) => void change(tool, e.target.checked)} />
              {vendorLabel(tool)}
            </label>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-300">
          {error}
        </p>
      )}
    </section>
  );
}
