'use client';

/** Downloads the privileged account list: every administrator (of one client, or of all) with Multi-Factor and last sign-in, riskiest first, as a CSV. Reads the list page by page, so it can take a moment. */
import { useState } from 'react';
import { identitiesApi, type IdentityPerson } from '@/lib/api';
import { privilegedCsv, privilegedRows } from '@/lib/privilegedReport';
import { saveText } from '@/lib/saveFile';

/** The most pages read (200 people each), so a very large estate cannot keep the browser busy for long. */
export const MAX_PAGES = 25;

export function PrivilegedExport({ clientId }: { clientId: string }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [partial, setPartial] = useState(false);
  const run = async () => {
    setBusy(true);
    setProblem('');
    setPartial(false);
    try {
      const people: IdentityPerson[] = [];
      for (let page = 1; page <= MAX_PAGES; page++) {
        const res = await identitiesApi.list({ admin: true, clientId: clientId || undefined, page, pageSize: 200 });
        people.push(...res.items);
        if (page >= res.pages) break;
        if (page === MAX_PAGES) setPartial(true);
      }
      await saveText('privileged-accounts.csv', privilegedCsv(privilegedRows(people)));
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : 'Could not build the list.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button type="button" disabled={busy} onClick={() => void run()} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50">
        {busy ? 'Building the list...' : 'Download administrators (CSV)'}
      </button>
      {partial && <span className="text-xs text-amber-300">Only the first {MAX_PAGES * 200} administrators are in the file.</span>}
      {problem && (
        <span role="alert" className="text-xs text-red-300">
          {problem}
        </span>
      )}
    </span>
  );
}
