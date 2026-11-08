'use client';

/**
 * Settings > Workspace: private status-page links for clients. Make a link for a client (its secret is shown once), PREVIEW exactly what the client will see, approve that wording, and revoke when
 * needed. A link does nothing until its wording is approved. Making, approving and revoking are a person's acts, which the server enforces.
 */
import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { apiErrorDetail, clientStatusLinksApi, type ClientStatusPreview } from '@/lib/api';

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function ClientStatusLinks() {
  const list = useSWR('client-status-links', () => clientStatusLinksApi.list(), { revalidateOnFocus: false, shouldRetryOnError: false });
  const [clientId, setClientId] = useState('');
  const [label, setLabel] = useState('');
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ token: string; name: string | null } | null>(null);
  const [preview, setPreview] = useState<{ id: string; page: ClientStatusPreview } | null>(null);

  const fail = (err: unknown, fallback: string) => toast.error(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : fallback));
  const run = async (what: () => Promise<void>, fallback: string) => {
    setBusy(true);
    try {
      await what();
    } catch (err) {
      fail(err, fallback);
    } finally {
      setBusy(false);
    }
  };

  if (list.error) return <p className="mt-6 text-sm text-gray-500" data-testid="status-links-error">The client status links could not be loaded.</p>;
  if (!list.data) return null;
  const data = list.data;
  const chosen = clientId || data.clients[0]?.id || '';
  const address = (token: string) => `${typeof window === 'undefined' ? '' : window.location.origin}/status/${token}`;

  return (
    <section className="mt-6 rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="status-links">
      <h3 className="text-sm font-semibold text-gray-100">Client status pages</h3>
      <p className="mt-1 text-xs text-gray-400">
        A private link a client can open with no sign-in, showing counts only: protection coverage, open alerts and the protections in place. Never raw alerts, names, devices or tickets. Preview it, approve the wording, then send the link.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-400">
          Client
          <select className={`${input} mt-1 block`} value={chosen} onChange={(e) => setClientId(e.target.value)}>
            {data.clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Label
          <input className={`${input} mt-1 block`} value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          Days
          <input type="number" min={1} max={365} className={`${input} mt-1 block w-20`} value={days} onChange={(e) => setDays(Math.max(1, Math.min(365, Number(e.target.value) || data.default_days)))} />
        </label>
        <button
          type="button"
          className={ghost}
          disabled={busy || !chosen}
          onClick={() =>
            void run(async () => {
              const made = await clientStatusLinksApi.create({ client_id: chosen, label: label.trim(), days });
              setSecret({ token: made.token, name: made.client_name });
              setLabel('');
              await list.mutate();
            }, 'Could not make the link.')
          }
        >
          Make a link
        </button>
      </div>
      {secret ? (
        <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="status-secret">
          <div className="text-amber-200">The link for {secret.name ?? 'this client'}. It is shown once; copy it now. It does nothing until you approve its wording below.</div>
          <code className="mt-1 block break-all text-xs text-gray-100">{address(secret.token)}</code>
        </div>
      ) : null}
      {data.links.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500" data-testid="status-links-empty">No links yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-800 text-sm">
          {data.links.map((l) => (
            <li key={l.id} className="py-2" data-testid={`status-link-${l.id}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-gray-200">
                  {l.client_name ?? 'Client'}{l.label ? ` (${l.label})` : ''} · until {l.expires_at.slice(0, 10)} · <span className={l.state === 'live' ? 'text-emerald-300' : 'text-gray-400'}>{l.state}</span>
                  {l.last_opened_at ? ` · last opened ${l.last_opened_at.slice(0, 10)}` : ''}
                </span>
                <span className="flex gap-2">
                  <button type="button" className={ghost} disabled={busy} onClick={() => void run(async () => setPreview({ id: l.id, page: await clientStatusLinksApi.preview(l.id) }), 'Could not load the preview.')}>Preview</button>
                  {!l.reviewed_at && !l.revoked_at ? (
                    <button type="button" className={ghost} disabled={busy} onClick={() => void run(async () => { await clientStatusLinksApi.review(l.id); await list.mutate(); }, 'Could not approve it.')}>Approve wording</button>
                  ) : null}
                  {!l.revoked_at ? (
                    <button type="button" className={ghost} disabled={busy} onClick={() => void run(async () => { await clientStatusLinksApi.revoke(l.id); await list.mutate(); }, 'Could not revoke it.')}>Revoke</button>
                  ) : null}
                </span>
              </div>
              {preview?.id === l.id ? (
                <div className="mt-2 rounded border border-gray-700 bg-gray-950/60 p-3 text-xs text-gray-300" data-testid="status-preview">
                  <div className="font-semibold text-gray-100">{preview.page.copy.title}{preview.page.client_name ? ` · ${preview.page.client_name}` : ''}</div>
                  <p className="mt-1">{preview.page.copy.intro}</p>
                  <p className="mt-1">{preview.page.copy.devices}: {preview.page.devices.percent === null ? 'not available yet' : `${preview.page.devices.percent}% (${preview.page.devices.protected} of ${preview.page.devices.total})`}</p>
                  <p>{preview.page.copy.people}: {preview.page.people === null || preview.page.people.percent === null ? 'not available yet' : `${preview.page.people.percent}% (${preview.page.people.protected} of ${preview.page.people.total})`}</p>
                  <p>{preview.page.copy.alerts_open}: {preview.page.alerts.open}{preview.page.alerts.open > 0 ? `, ${preview.page.alerts.being_worked_on} ${preview.page.copy.alerts_handled}` : ''}</p>
                  {preview.page.tools.length > 0 ? <p>{preview.page.copy.tools}: {preview.page.tools.join('; ')}</p> : null}
                  <p className="mt-1 text-gray-500">{preview.page.copy.footer}</p>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
