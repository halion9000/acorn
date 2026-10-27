'use client';

/**
 * The owner's tools that are set up in CORE, listed on the Connectors page as connected.
 *
 * CORE holds the credentials for these (Huntress, NinjaOne, Petra...) and tells A.C.O.R.N which are connected, so nothing is entered twice and nothing here can be edited: the card says so.
 * Tools CORE has not connected are kept out of sight in a closed list. Shows nothing until CORE has reported at least once, and nothing when the list cannot be loaded (the page still works).
 */
import useSWR from 'swr';

import { connectorsApi, type CoreTool } from '@/lib/api';

export function CoreToolsPanel() {
  const { data } = useSWR<CoreTool[]>('connectors:core-tools', () => connectorsApi.coreTools(), { revalidateOnFocus: false, shouldRetryOnError: false });
  const tools = data ?? [];
  if (tools.length === 0) return null;
  const connected = tools.filter((t) => t.connected);
  const idle = tools.filter((t) => !t.connected);

  return (
    <section aria-label="Connected in CORE" data-testid="core-tools-panel" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-gray-200">Connected in CORE</h2>
        <p className="text-xs text-gray-500">
          These tools are set up in CORE, which holds their credentials and sends their alerts, devices and counts here. There is nothing to set up again.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {connected.map((t) => (
          <li key={t.tool_id} className="rounded-xl border border-gray-800/60 bg-gray-900/60 p-4" data-testid="core-tool">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium text-gray-100">{t.title}</span>
              <span className="shrink-0 rounded border border-green-500/40 bg-green-500/10 px-1.5 py-0.5 text-[11px] text-green-300">Connected</span>
            </div>
            {t.description && <p className="mt-1 line-clamp-2 text-xs text-gray-500">{t.description}</p>}
            <p className="mt-2 text-[11px] text-gray-600">Managed in CORE</p>
          </li>
        ))}
      </ul>
      {connected.length === 0 && <p className="text-xs text-gray-500">None of the tools in CORE are connected yet.</p>}
      {idle.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer text-gray-400">
            {idle.length} tool{idle.length === 1 ? '' : 's'} in CORE not connected
          </summary>
          <ul className="mt-2 flex flex-wrap gap-2">
            {idle.map((t) => (
              <li key={t.tool_id} className="rounded border border-gray-800 px-2 py-0.5" data-testid="core-tool-idle">
                {t.title}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
