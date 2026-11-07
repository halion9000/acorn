'use client';

/**
 * "Auto-ticket": a button in the alert's top row, next to "Hide alert type". It opens a small window that makes a rule from this alert: from now on every new alert of this type that has no HaloPSA ticket gets
 * one (opened by CORE), for this client or for every client, and this alert gets one now if it has none. It asks first, because it acts on its own afterwards. The rules are listed (and turned off) under
 * Settings, Tickets.
 */

import { useState } from 'react';
import toast from 'react-hot-toast';
import { ticketRulesApi } from '@/lib/api';

export function TicketRuleButton({ alertId, clientName }: { alertId: string; clientName?: string | null }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<'client' | 'all'>('client');
  const [catchUp, setCatchUp] = useState(true);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState(false);

  async function make() {
    setBusy(true);
    try {
      const rule = await ticketRulesApi.make(alertId, scope, catchUp);
      setMade(true);
      setOpen(false);
      const n = rule.queued_now ?? 0;
      toast.success(n > 1 ? `Rule made. ${n} tickets are being opened (this alert and the others of its type that were open).` : n === 1 ? 'Rule made. A ticket for this alert is being opened.' : 'Rule made. New alerts of this type will get a ticket.');
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
        title="Open a HaloPSA ticket and a case automatically for every alert of this type"
        className="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 text-sm px-3 py-1.5 rounded-lg transition-colors"
        data-testid="ticket-rule-open"
      >
        {made ? 'Auto-ticket: on' : 'Auto-ticket'}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label="Open a ticket for alerts like this" onClick={() => !busy && setOpen(false)}>
          <div className="w-full max-w-md space-y-3 rounded-xl border border-gray-800 bg-gray-900 p-5 text-sm text-gray-300 shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="ticket-rule-form">
            <h2 className="text-base font-semibold text-white">Open a ticket for alerts like this</h2>
            <p>From now on, open a HaloPSA ticket and a case for every new alert of this type that has none. CORE opens the ticket and its number is linked here; the case appears under Cases. Make or turn off rules under Settings, Tickets.</p>
            <label className="flex items-center gap-2">
              <input type="radio" name="ticket-rule-scope" checked={scope === 'client'} onChange={() => setScope('client')} />
              <span>for {clientName ? clientName : 'this client'} only</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="ticket-rule-scope" checked={scope === 'all'} onChange={() => setScope('all')} />
              <span>for every client</span>
            </label>
            <label className="flex items-start gap-2 border-t border-gray-800 pt-3">
              <input type="checkbox" className="mt-1" checked={catchUp} onChange={(e) => setCatchUp(e.target.checked)} />
              <span>Also open tickets and cases, once, for the alerts of this type that are already open and have none (up to 25, newest first). Without this, only this alert and new ones get them.</span>
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" disabled={busy} onClick={() => setOpen(false)} className="rounded-lg px-4 py-2 text-gray-300 hover:bg-gray-800">
                Cancel
              </button>
              <button type="button" disabled={busy} onClick={() => void make()} className="rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-500 disabled:opacity-50">
                {busy ? 'Making…' : 'Make the rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
