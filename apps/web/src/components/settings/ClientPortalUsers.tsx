'use client';

/**
 * Settings > Workspace > Client dashboard sign-ins: the MSP's staff create, reset and turn off the sign-ins of people at their clients, who then see only their own company's summary at /client-portal.
 * Each starts with a temporary password shown once (give it to the person another way) and needs an authenticator app before the dashboard opens. Hidden for anyone the server refuses (it checks every action itself).
 */
import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';

import { apiErrorDetail, clientPortalApi, msspApi, type ChildTenant, type ClientPortalUser } from '@/lib/api';

const input = 'w-full rounded-md border border-gray-700 bg-gray-950/60 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600';
const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800';

export function ClientPortalUsers() {
  const [users, setUsers] = useState<ClientPortalUser[] | null>(null);
  const [hidden, setHidden] = useState(false);
  const [clients, setClients] = useState<ChildTenant[]>([]);
  const [adding, setAdding] = useState(false);
  const [clientId, setClientId] = useState('');
  const [account, setAccount] = useState('');
  const [email, setEmail] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<{ account: string; password: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await clientPortalApi.users());
    } catch {
      setHidden(true); // not permitted (or not an MSP): nothing to show
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (adding && clients.length === 0) void msspApi.listChildren().then(setClients).catch(() => setClients([]));
  }, [adding, clients.length]);

  if (hidden || users === null) return null;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setProblem(null);
    try {
      const r = await clientPortalApi.create({ child_tenant_id: clientId, account_name: account.trim(), ...(email.trim() ? { email: email.trim() } : {}) });
      setMade({ account: r.account_name, password: r.temporary_password });
      setAdding(false);
      setAccount('');
      setEmail('');
      await load();
    } catch (err) {
      setProblem(apiErrorDetail(err) ?? 'Could not create the sign-in.');
    }
  };
  const act = async (what: 'reset' | 'off', u: ClientPortalUser) => {
    if (what === 'off' && !window.confirm(`Turn off ${u.account_name} (${u.client_name})? They are signed out and cannot sign in again.`)) return;
    try {
      const r = what === 'reset' ? await clientPortalApi.resetMfa(u.id) : await clientPortalApi.turnOff(u.id);
      toast.success(r.detail);
      await load();
    } catch (err) {
      toast.error(apiErrorDetail(err) ?? 'That did not work.');
    }
  };

  return (
    <div className="border-t border-gray-800 px-6 py-5" data-testid="client-portal-users">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-200">Client dashboard sign-ins</h3>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500">
            Add a client sign-in
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-gray-500">
        People at your clients who sign in at /client-portal to see only their own company&apos;s tickets, hours and satisfaction. Each needs an authenticator app before the dashboard opens, and the client must be linked to a HaloPSA client
        first.
      </p>
      {made && (
        <p role="status" className="mt-2 rounded border border-emerald-700 bg-emerald-900/20 p-2 text-xs text-emerald-200" data-testid="portal-temp-password">
          Created {made.account}. Temporary password (shown once, give it to them another way): <span className="font-mono">{made.password}</span>
        </p>
      )}
      {adding && (
        <form className="mt-3 grid gap-3 sm:grid-cols-3" onSubmit={(e) => void create(e)}>
          <label className="text-xs text-gray-300">
            Client
            <select aria-label="Client" className={`${input} mt-1`} value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">Choose a client</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-300">
            Account name
            <input aria-label="Account name" className={`${input} mt-1`} value={account} onChange={(e) => setAccount(e.target.value)} />
          </label>
          <label className="text-xs text-gray-300">
            Email (optional)
            <input aria-label="Email" className={`${input} mt-1`} value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <div className="flex items-center gap-2 sm:col-span-3">
            <button type="submit" disabled={!clientId || !account.trim()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50">
              Create sign-in
            </button>
            <button type="button" className={ghost} onClick={() => setAdding(false)}>
              Cancel
            </button>
            {problem && (
              <span role="alert" className="text-xs text-amber-300">
                {problem}
              </span>
            )}
          </div>
        </form>
      )}
      {users.length === 0 ? (
        <p className="mt-2 text-xs text-gray-500">No client sign-ins yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-800 text-sm">
          {users.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="text-gray-100">
                  {u.account_name} <span className="text-xs text-gray-400">at {u.client_name}</span>
                </p>
                <p className="text-xs text-gray-500">
                  {u.is_active ? 'Active' : 'Turned off'}; {u.mfa_enabled ? 'authenticator app set up' : 'no authenticator app yet (the dashboard stays closed)'}
                  {u.last_login ? `; last sign-in ${u.last_login.slice(0, 10)}` : '; never signed in'}
                </p>
              </div>
              {u.is_active && (
                <div className="flex gap-2">
                  <button type="button" className={ghost} onClick={() => void act('reset', u)}>
                    Reset second step
                  </button>
                  <button type="button" className={ghost} onClick={() => void act('off', u)}>
                    Turn off
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
