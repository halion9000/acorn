'use client';

/**
 * Chooses whose data a page shows: this organisation's own, or one of its clients. Nothing is drawn for an organisation with no clients, so an ordinary tenant sees no change.
 * The value is the client's tenant id, or '' for the organisation's own.
 */
import useSWR from 'swr';

import { msspApi } from '@/lib/api';

export function ClientPicker({ value, onChange, ownLabel = 'My organisation (internal)', label = 'Show' }: { value: string; onChange: (clientId: string) => void; ownLabel?: string; label?: string }) {
  const { data: clients } = useSWR(['client-picker'], () => msspApi.listChildren().catch(() => []));
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
        <option value="">{ownLabel}</option>
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
