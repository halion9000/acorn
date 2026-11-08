/**
 * The client's private status page (`/status/<secret>`): what the API returns for it, and the server-side fetch.
 * The API decides everything a client may read (counts and plain labels only, see services/api/app/services/client_status.py); this only draws it.
 */

export interface ClientStatusPage {
  client_name: string;
  generated_at: string | null;
  devices: { total: number; protected: number; percent: number | null };
  people: { total: number; protected: number; percent: number | null } | null;
  alerts: { open: number; being_worked_on: number };
  tools: string[];
  copy: Record<'title' | 'intro' | 'devices' | 'people' | 'alerts_open' | 'alerts_handled' | 'tools' | 'footer', string>;
}

function apiBase(): string {
  return (process.env.API_URL || process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
}

/** Server-side fetch of one client's page; null for any problem (the API gives the same 404 for a wrong, revoked, expired or unreviewed link). Never cached. */
export async function fetchClientStatus(token: string): Promise<ClientStatusPage | null> {
  try {
    const res = await fetch(`${apiBase()}/api/v1/public/client-status/${encodeURIComponent(token)}`, { cache: 'no-store' });
    if (!res.ok) return null;
    return (await res.json()) as ClientStatusPage;
  } catch {
    return null;
  }
}
