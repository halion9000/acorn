'use client';

/**
 * "Auto-run script": a button in the alert's top row, next to "Auto-ticket". It opens a small window that makes a rule from this alert: from now on, for every new alert of this type, run the Windows script on a
 * Windows machine and the Mac script on a Mac (scripts CORE has switched on), for this client or for every client, and run it for this alert now. It asks first, because it acts on a client's machine on its own
 * afterwards. Whether a run starts at once or waits for an approval card is CORE's decision for each script, and the window says which. Only NinjaOne-managed machines are run on. The rules are listed (and turned
 * off) under Settings, Tickets.
 */

import { useState } from 'react';
import toast from 'react-hot-toast';
import useSWR from 'swr';
import { alertsApi, scriptRulesApi } from '@/lib/api';

const TOOLS: { value: string; label: string }[] = [
  { value: '', label: 'No condition' },
  { value: 'screenconnect', label: 'ScreenConnect' },
  { value: 'huntress', label: 'Huntress' },
  { value: 'fieldeffect', label: 'Field Effect' },
];

export function ScriptRuleButton({ alertId, clientName }: { alertId: string; clientName?: string | null }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<'client' | 'all'>('client');
  const [windows, setWindows] = useState('');
  const [mac, setMac] = useState('');
  const [tool, setTool] = useState('');
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState(false);
  const { data } = useSWR(open ? ['alerts', alertId, 'script-options'] : null, () => alertsApi.scriptOptions(alertId), { shouldRetryOnError: false, revalidateOnFocus: false });
  const scripts = data?.scripts ?? [];
  const byId = (id: string) => scripts.find((s) => String(s.id) === id);
  const approval = (id: string) => (byId(id)?.one_click ? 'runs at once' : 'asks for your approval in CORE first');

  async function make() {
    setBusy(true);
    try {
      const rule = await scriptRulesApi.make({ alert_id: alertId, scope, windows_script_id: windows ? Number(windows) : undefined, mac_script_id: mac ? Number(mac) : undefined, requires_tool: tool || undefined });
      setMade(true);
      setOpen(false);
      const n = rule.queued_now ?? 0;
      toast.success(n > 0 ? `Rule made. ${n} script request${n === 1 ? ' is' : 's are'} on its way to CORE.` : 'Rule made. New alerts of this type will run the script (a machine it cannot run on is noted on the alert).');
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not make the rule.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Run a script automatically for every alert of this type, the Windows or Mac one by the machine"
        className="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded-lg transition-colors"
        data-testid="script-rule-open"
      >
        {made ? 'Auto-run script: on' : 'Auto-run script'}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label="Run a script for alerts like this" onClick={() => !busy && setOpen(false)}>
          <div className="w-full max-w-md space-y-3 rounded-xl border border-gray-800 bg-gray-900 p-5 text-sm text-gray-300 shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="script-rule-form">
            <h2 className="text-base font-semibold text-white">Run a script for alerts like this</h2>
            <p>From now on, for every new alert of this type, CORE runs the Windows script on a Windows machine and the Mac script on a Mac, and puts the result on the alert&apos;s HaloPSA ticket. Only machines NinjaOne manages are run on.</p>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-400">Script for Windows machines</span>
              <select value={windows} onChange={(e) => setWindows(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Windows script">
                <option value="">None (leave Windows machines alone)</option>
                {scripts.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              {windows ? <span className="text-xs text-gray-500">This script {approval(windows)}.</span> : null}
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-400">Script for Mac machines</span>
              <select value={mac} onChange={(e) => setMac(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Mac script">
                <option value="">None (leave Macs alone)</option>
                {scripts.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              {mac ? <span className="text-xs text-gray-500">This script {approval(mac)}.</span> : null}
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-400">Only when the client already uses</span>
              <select value={tool} onChange={(e) => setTool(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5" aria-label="Only when the client already uses">
                {TOOLS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <span className="text-xs text-gray-500">Checked against the client&apos;s machines in A.C.O.R.N: at least one must have the tool. A client that does not is skipped.</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="script-rule-scope" checked={scope === 'client'} onChange={() => setScope('client')} />
              <span>for {clientName ? clientName : 'this client'} only</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="script-rule-scope" checked={scope === 'all'} onChange={() => setScope('all')} />
              <span>for every client</span>
            </label>
            {scripts.length === 0 && data ? <p className="text-amber-300">CORE has not switched any script on, so there is nothing to choose. Switch scripts on in CORE first.</p> : null}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" disabled={busy} onClick={() => setOpen(false)} className="rounded-lg px-4 py-2 text-gray-300 hover:bg-gray-800">
                Cancel
              </button>
              <button type="button" disabled={busy || (!windows && !mac)} onClick={() => void make()} className="rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-500 disabled:opacity-50">
                {busy ? 'Making…' : 'Make the rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
