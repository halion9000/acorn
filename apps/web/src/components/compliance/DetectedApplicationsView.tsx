'use client';

/**
 * Detected applications: the apps found in the client's Microsoft 365 tenant, for a person to deal with. Add makes a vendor of it, Ignore hides it, Link joins it to a vendor already listed so several apps of one
 * vendor show as one on the vendor page. Newest first, ten to a page.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, detectedAppsApi, type DetectedApp, type DetectedAppList } from '@/lib/api';

type Show = 'new' | 'linked' | 'ignored' | 'all';
const PAGE = 10;
const LABEL: Record<Show, string> = { new: 'To review', linked: 'Added or linked', ignored: 'Ignored', all: 'All' };

export function DetectedApplicationsView() {
  const [clientId, setClientId] = useState('');
  const [show, setShow] = useState<Show>('new');
  const [data, setData] = useState<DetectedAppList | null>(null);
  const [problem, setProblem] = useState('');
  const [page, setPage] = useState(0);
  const [linking, setLinking] = useState<string | null>(null);
  const [vendorId, setVendorId] = useState('');

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  const load = useCallback(async () => {
    try {
      // "Added or linked" asks for everything and keeps those two kinds.
      setData(await detectedAppsApi.list(clientId, show === 'linked' ? 'all' : show));
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the applications.'));
    }
  }, [clientId, show]);

  useEffect(() => {
    setData(null);
    setPage(0);
    void load();
  }, [load]);

  const act = async (work: () => Promise<DetectedApp>) => {
    try {
      await work();
      setLinking(null);
      setVendorId('');
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'That did not work.');
    }
  };

  const rows = (data?.apps ?? []).filter((a) => (show === 'linked' ? a.status === 'added' || a.status === 'linked' : true));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800';

  return (
    <div className="space-y-4 p-6">
      <div>
        <a href={clientId ? `/compliance/vendors?client=${encodeURIComponent(clientId)}` : '/compliance/vendors'} className="text-xs text-blue-300 hover:underline">
          Vendors
        </a>
        <h1 className="text-2xl font-bold text-white">Detected applications</h1>
        <p className="mt-1 text-sm text-gray-400">Apps people in the Microsoft 365 tenant agreed to use. Add one as a vendor, ignore it, or link it to a vendor you already have so they show as one.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose applications" />
        </div>
      </div>
      <div role="tablist" className="flex gap-1 border-b border-gray-800">
        {(Object.keys(LABEL) as Show[]).map((t) => (
          <button key={t} role="tab" aria-selected={show === t} type="button" onClick={() => setShow(t)} className={`px-3 py-1.5 text-sm ${show === t ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
            {LABEL[t]}
            {data && t === 'new' ? ` (${data.counts.new})` : ''}
          </button>
        ))}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && rows.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="detected-empty">
          {show === 'new' ? 'Nothing is waiting. New applications appear here after the next read of the Microsoft 365 tenant.' : 'Nothing here.'}
        </p>
      )}
      {data && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="detected-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Date detected</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Accounts</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {shown.map((a) => (
                <tr key={a.id} data-testid="detected-row">
                  <td className="px-3 py-2 text-gray-100">
                    {a.name}
                    {a.risky && <span className="ml-2 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-300">risky permission</span>}
                    {a.vendor_name && <div className="text-xs text-gray-500">{a.status === 'added' ? 'Added as' : 'Linked to'} {a.vendor_name}</div>}
                  </td>
                  <td className="px-3 py-2 text-gray-300">{a.first_seen.slice(0, 10)}</td>
                  <td className="px-3 py-2 text-gray-300">{a.source_label}</td>
                  <td className="px-3 py-2 text-gray-300">{a.accounts.toLocaleString()}</td>
                  <td className="px-3 py-2">
                    {a.status === 'new' ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" aria-label={`Add ${a.name}`} onClick={() => void act(() => detectedAppsApi.add(clientId, a.id))} className="rounded bg-gray-100 px-3 py-1 text-xs font-medium text-gray-900 hover:bg-white">
                          Add
                        </button>
                        <button type="button" aria-label={`Ignore ${a.name}`} onClick={() => void act(() => detectedAppsApi.ignore(clientId, a.id))} className={btn}>
                          Ignore
                        </button>
                        <button type="button" aria-label={`Link ${a.name}`} onClick={() => { setLinking(linking === a.id ? null : a.id); setVendorId(''); }} className="text-xs text-blue-300 hover:underline">
                          Link
                        </button>
                        {linking === a.id && (
                          <span className="flex items-center gap-1">
                            <select aria-label={`Vendor to link ${a.name} to`} value={vendorId} onChange={(e) => setVendorId(e.target.value)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-100">
                              <option value="">Choose a vendor</option>
                              {data.vendors.map((v) => (
                                <option key={v.id} value={v.id}>
                                  {v.name}
                                </option>
                              ))}
                            </select>
                            <button type="button" disabled={!vendorId} onClick={() => void act(() => detectedAppsApi.link(clientId, a.id, vendorId))} className={`${btn} disabled:opacity-40`}>
                              Link it
                            </button>
                          </span>
                        )}
                      </div>
                    ) : a.status === 'added' ? (
                      <span className="text-xs text-gray-500">Added</span>
                    ) : (
                      <button type="button" aria-label={`Bring back ${a.name}`} onClick={() => void act(() => detectedAppsApi.restore(clientId, a.id))} className={btn}>
                        Bring back
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > PAGE && (
        <div className="flex items-center gap-3 text-xs text-gray-400" data-testid="detected-pager">
          <span>
            {page * PAGE + 1} - {Math.min(rows.length, (page + 1) * PAGE)} of {rows.length} items
          </span>
          <button type="button" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)} className={`${btn} disabled:opacity-40`}>
            Previous
          </button>
          <button type="button" aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} className={`${btn} disabled:opacity-40`}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}
