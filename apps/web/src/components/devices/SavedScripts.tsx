'use client';

/**
 * Saved scripts for one machine (reboot, flush DNS, gpupdate...): pick one and run it through ScreenConnect after a confirm. Running needs the scripts:run permission, which a role is given on purpose; adding,
 * switching off and deleting scripts needs the console permission. Nothing is typed here, so a person who may only run scripts cannot send anything else.
 */
import { useCallback, useEffect, useState } from 'react';

import { apiErrorDetail, savedScriptsApi, type SavedScript } from '@/lib/api';

const btn = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';
const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-100';

export function SavedScripts({ deviceId, hostname, onSent }: { deviceId: string; hostname: string; onSent?: () => void }) {
  const [scripts, setScripts] = useState<SavedScript[] | null>(null);
  const [picked, setPicked] = useState('');
  const [message, setMessage] = useState('');
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', command: '' });

  const load = useCallback(async () => {
    try {
      const rows = await savedScriptsApi.list();
      setScripts(rows);
      setPicked((p) => (rows.some((r) => r.id === p && r.enabled) ? p : (rows.find((r) => r.enabled)?.id ?? '')));
    } catch {
      setScripts([]); // not allowed to see or run scripts: nothing is shown
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<void>) => {
    setMessage('');
    try {
      await work();
    } catch (e) {
      setMessage(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };

  if (scripts === null) return null;
  const chosen = scripts.find((s) => s.id === picked);
  const run = () =>
    act(async () => {
      if (!chosen || !window.confirm(`Run "${chosen.name}" on ${hostname}? It runs on the machine as SYSTEM.`)) return;
      const [result] = await savedScriptsApi.run(chosen.id, [deviceId]);
      setMessage(result?.refused ? `Not sent: ${result.refused}` : `Sent "${chosen.name}". The answer appears in the command prompt.`);
      onSent?.();
    });

  return (
    <div className="space-y-2 text-xs" data-testid="saved-scripts" onClick={(e) => e.stopPropagation()}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-gray-400">Saved scripts</span>
        {scripts.some((s) => s.enabled) ? (
          <>
            <select aria-label="Saved script" className={field} value={picked} onChange={(e) => setPicked(e.target.value)}>
              {scripts
                .filter((s) => s.enabled)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
            <button type="button" className={btn} disabled={!chosen} onClick={() => void run()}>
              Run on this machine
            </button>
          </>
        ) : (
          <span className="text-gray-500">none switched on</span>
        )}
        <button type="button" className="text-blue-300 hover:underline" onClick={() => setAdding((v) => !v)}>
          {adding ? 'Close' : 'Manage'}
        </button>
      </div>
      {adding && (
        <div className="space-y-2 rounded border border-gray-800 p-2" data-testid="manage-scripts">
          <ul className="space-y-1">
            {scripts.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-2">
                <span className="text-gray-200">
                  {s.name} <span className="font-mono text-gray-500">{s.command}</span> {s.enabled ? '' : '(off)'}
                </span>
                <span className="flex gap-1">
                  <button
                    type="button"
                    className={btn}
                    aria-label={`${s.enabled ? 'Switch off' : 'Switch on'} ${s.name}`}
                    onClick={() =>
                      void act(async () => {
                        await savedScriptsApi.patch(s.id, { enabled: !s.enabled });
                        await load();
                      })
                    }
                  >
                    {s.enabled ? 'Switch off' : 'Switch on'}
                  </button>
                  <button
                    type="button"
                    className={btn}
                    aria-label={`Delete ${s.name}`}
                    onClick={() =>
                      void act(async () => {
                        await savedScriptsApi.remove(s.id);
                        await load();
                      })
                    }
                  >
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                await savedScriptsApi.create({ name: form.name.trim(), command: form.command.trim() });
                setForm({ name: '', command: '' });
                await load();
              });
            }}
          >
            <label className="text-gray-400">
              Name
              <input className={`${field} mt-1 block`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="text-gray-400">
              Command
              <input className={`${field} mt-1 block font-mono`} value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} />
            </label>
            <button type="submit" className={btn} disabled={form.name.trim().length < 2 || !form.command.trim()}>
              Save script
            </button>
          </form>
        </div>
      )}
      {message && (
        <p role="status" className="text-amber-300">
          {message}
        </p>
      )}
    </div>
  );
}
