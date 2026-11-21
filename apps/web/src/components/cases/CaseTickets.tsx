'use client';

/**
 * The HaloPSA tickets a case is linked to. A case should always have one: an alert's ticket rule links the ticket it opens, and a case opened by hand gets one here, by linking a ticket number or asking for a new
 * ticket to be opened (CORE opens it and its number appears on the case within a few minutes).
 */
import { useState } from 'react';
import toast from 'react-hot-toast';

import { apiErrorDetail, casesApi, type Case } from '@/lib/api';

const field = 'w-28 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white focus:border-emerald-500 focus:outline-none';
const button = 'rounded-md border border-slate-700/70 bg-slate-900/60 px-2.5 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-500';

export function CaseTickets({ caseId, tickets, onChanged }: { caseId: string; tickets: NonNullable<Case['tickets']>; onChanged: () => void }) {
  const [number, setNumber] = useState('');
  const [busy, setBusy] = useState(false);

  const run = async (work: () => Promise<string | void>) => {
    setBusy(true);
    try {
      const said = await work();
      if (said) toast.success(said);
      onChanged();
    } catch (err) {
      toast.error(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : 'That did not work. Try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-800/60 pt-3 text-xs" data-testid="case-tickets">
      <span className="text-[11px] uppercase tracking-wide text-slate-500">Tickets</span>
      {tickets.length > 0 ? (
        tickets.map((t) => (
          <span key={t.id} className="rounded-full bg-slate-800 px-2.5 py-0.5 font-mono text-slate-200" title={t.addedBy ? `Linked by ${t.addedBy}` : undefined}>
            #{t.id}
          </span>
        ))
      ) : (
        <span className="text-amber-300" data-testid="case-no-ticket">
          No ticket yet. A case should always be tied to one.
        </span>
      )}
      <input aria-label="HaloPSA ticket number" className={field} placeholder="Ticket number" inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value)} />
      <button
        type="button"
        className={button}
        disabled={busy || !number.trim()}
        onClick={() =>
          void run(async () => {
            await casesApi.linkTicket(caseId, number.trim());
            setNumber('');
            return 'Ticket linked';
          })
        }
      >
        Link ticket
      </button>
      <button type="button" className={button} disabled={busy} onClick={() => void run(() => casesApi.createTicket(caseId))}>
        Open a new ticket
      </button>
    </div>
  );
}
