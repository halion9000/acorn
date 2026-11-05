'use client';

/**
 * "Open a HaloPSA ticket for alerts like this": makes a rule from this alert, for its client or for every client. From then on each new alert of the type that has no ticket gets one (opened by CORE),
 * and this alert gets one now if it has none. Asks first, because it acts on its own afterwards. The rules are listed (and can be turned off) under Settings, Tickets.
 */

import { useState } from 'react';
import toast from 'react-hot-toast';
import { ticketRulesApi } from '@/lib/api';

export function TicketRuleButton({ alertId, clientName }: { alertId: string; clientName?: string | null }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<'client' | 'all'>('client');
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState(false);

  async function make() {
    setBusy(true);
    try {
      const rule = await ticketRulesApi.make(alertId, scope);
      setMade(true);
      setOpen(false);
      toast.success(rule.queued_now ? 'Rule made. A ticket for this alert is being opened.' : 'Rule made. New alerts of this type will get a ticket.');
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not make the rule.');
    } finally {
      setBusy(false);
    }
  }

  if (made) return <p className="text-xs text-green-300" data-testid="ticket-rule-made">A ticket rule is on for this type of alert. See Settings, Tickets.</p>;
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="text-xs text-gray-400 hover:text-gray-200" data-testid="ticket-rule-open">
        Open a ticket for alerts like this…
      </button>
    );
  }
  return (
    <div className="space-y-2 rounded border border-gray-700 p-3 text-sm text-gray-300" data-testid="ticket-rule-form">
      <p>From now on, open a HaloPSA ticket for every new alert of this type that has none:</p>
      <label className="flex items-center gap-2">
        <input type="radio" name="ticket-rule-scope" checked={scope === 'client'} onChange={() => setScope('client')} />
        <span>for {clientName ? clientName : 'this client'} only</span>
      </label>
      <label className="flex items-center gap-2">
        <input type="radio" name="ticket-rule-scope" checked={scope === 'all'} onChange={() => setScope('all')} />
        <span>for every client</span>
      </label>
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => void make()} className="rounded border border-gray-600 px-3 py-1 text-gray-100 hover:bg-gray-800 disabled:opacity-50">
          {busy ? 'Making…' : 'Make the rule'}
        </button>
        <button type="button" disabled={busy} onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-200">
          Cancel
        </button>
      </div>
    </div>
  );
}
