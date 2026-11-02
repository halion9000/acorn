'use client';

/**
 * Settings > Roles & Permissions: the role a person gets the first time they sign in with Microsoft and have no account yet. A built-in role (never Administrator) or one of this workspace's custom
 * roles, which is then held on top of Viewer. Shown only when Microsoft sign-in is set up on the server; the server checks everything again and says why when it refuses.
 */
import { useEffect, useState } from 'react';
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';
import { failureDetail } from '@/lib/failure-detail';

interface SsoDefault {
  sso_configured: boolean;
  applies_here: boolean;
  role: string;
  custom_role_id: string | null;
  source: 'setting' | 'server';
  allowed_builtin: string[];
}

const LABELS: Record<string, string> = { viewer: 'Viewer', soc_analyst: 'SOC analyst', threat_hunter: 'Threat hunter', soc_lead: 'SOC lead' };
const CUSTOM = 'custom:';
const KEY = '/api/v1/rbac/sso-default';

const fetcher = async (url: string): Promise<SsoDefault> => {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export function SsoDefaultRoleCard({ customRoles }: { customRoles: { id: string; name: string }[] }) {
  const { data, mutate } = useSWR<SsoDefault>(KEY, fetcher, { shouldRetryOnError: false });
  const [choice, setChoice] = useState('viewer');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const current = data ? (data.custom_role_id ? CUSTOM + data.custom_role_id : data.role) : 'viewer';
  useEffect(() => setChoice(current), [current]);

  // Not set up on the server, or the read failed: there is nothing to choose, so the card stays out of the way.
  if (!data || !data.sso_configured) return null;

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const body = choice.startsWith(CUSTOM) ? { role: 'viewer', custom_role_id: choice.slice(CUSTOM.length) } : { role: choice, custom_role_id: null };
      const res = await authFetch(KEY, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(await failureDetail(res));
      await mutate(await res.json(), { revalidate: false });
      setMessage({ ok: true, text: 'Saved. The next new person who signs in with Microsoft gets this role.' });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof Error ? err.message : 'The change could not be saved.' });
    } finally {
      setBusy(false);
    }
  };

  const customName = (id: string) => customRoles.find((r) => r.id === id)?.name;
  return (
    <section aria-labelledby="sso-default-heading" className="rounded-xl border border-gray-800/60 bg-gray-900/60 p-5">
      <h3 id="sso-default-heading" className="text-sm font-semibold text-gray-200">
        Role for new Microsoft sign-ins
      </h3>
      <p className="mt-0.5 text-xs text-gray-500">
        The first time someone signs in with Microsoft and has no account yet, one is created with this role. Administrators are never made automatically. People who already have an account keep theirs.
      </p>
      {!data.applies_here ? (
        <p role="status" className="mt-3 text-xs text-amber-200">
          Microsoft sign-in creates new people in a different workspace, so this is set there, not here.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-gray-400">
            New people get
            <select
              aria-label="Role given to new people"
              value={choice}
              disabled={busy}
              onChange={(e) => setChoice(e.target.value)}
              className="mt-1 block w-64 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100"
            >
              <optgroup label="Built-in roles">
                {data.allowed_builtin.map((r) => (
                  <option key={r} value={r}>
                    {LABELS[r] ?? r}
                  </option>
                ))}
              </optgroup>
              {customRoles.length > 0 ? (
                <optgroup label="Your custom roles">
                  {customRoles.map((r) => (
                    <option key={r.id} value={CUSTOM + r.id}>
                      {r.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {data.custom_role_id && !customName(data.custom_role_id) ? <option value={CUSTOM + data.custom_role_id}>A custom role that no longer exists</option> : null}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || choice === current}
            onClick={() => void save()}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-800 disabled:text-gray-500"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
          <p className="text-xs text-gray-500">{data.source === 'setting' ? 'Chosen here.' : 'Not chosen here yet: the server setting applies (Viewer unless it says otherwise).'}</p>
        </div>
      )}
      {message ? (
        <p role={message.ok ? 'status' : 'alert'} className={`mt-2 text-xs ${message.ok ? 'text-emerald-300' : 'text-red-300'}`}>
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
