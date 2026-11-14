'use client';

/**
 * Chooses whose data a page shows: this organisation's own, or one of its clients. Nothing is drawn for an organisation with no clients, so an ordinary tenant sees no change.
 * The value is the client's tenant id. A page that gives an ``ownLabel`` ("All clients") gets that extra first choice with the value ''; without one there is no such choice: the organisation's own
 * company is one of the clients in the list (Live Oak IT Partners), so a picker with no ``ownLabel`` starts on it (or on the first client when there is none by that name) instead of on a "My organisation" line.
 */
import { useEffect } from 'react';
import useSWR from 'swr';

import { msspApi } from '@/lib/api';

/** The client the pickers start on: the organisation's own company, which is in the client list under its own name. */
export const HOME_CLIENT_NAME = 'live oak it partners';

export function homeClientId(clients: { id: string; name: string }[]): string {
  const sorted = [...clients].sort((a, b) => a.name.localeCompare(b.name));
  return (sorted.find((c) => c.name.trim().toLowerCase() === HOME_CLIENT_NAME) ?? sorted[0])?.id ?? '';
}

/** True when `clientId` is the organisation's own company (Live Oak IT Partners): the views that belong to the organisation itself (its own Secureframe, the organisation snapshot) stay on for it, as they were for the old "My organisation" line. */
export function useIsHomeClient(clientId: string): boolean {
  const { data: clients } = useSWR(['client-picker'], () => msspApi.listChildren().catch(() => []));
  return clientId !== '' && !!clients && homeClientId(clients) === clientId;
}

export function ClientPicker({ value, onChange, ownLabel, label = 'Show' }: { value: string; onChange: (clientId: string) => void; ownLabel?: string; label?: string }) {
  const { data: clients } = useSWR(['client-picker'], () => msspApi.listChildren().catch(() => []));
  const start = ownLabel === undefined && value === '' && clients && clients.length > 0 ? homeClientId(clients) : '';
  useEffect(() => {
    if (start) onChange(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);
  if (!clients || clients.length === 0) return null;
  const sorted = [...clients].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <label className="flex items-center gap-2 text-sm text-gray-300 print:hidden">
      {label}
      <select
        aria-label="Client"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-xs rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100"
      >
        {ownLabel !== undefined && <option value="">{ownLabel}</option>}
        {sorted.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The client named in the page's address (?client=<id>), for a link that opens on one client. */
export function clientFromAddress(search: string): string {
  return (new URLSearchParams(search).get('client') ?? '').slice(0, 64);
}
