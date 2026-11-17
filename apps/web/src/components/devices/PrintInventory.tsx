'use client';

/**
 * A client's device inventory laid out for paper: a title with the client and the date, the counts by kind, and one line per device (name, kind, make and model, serial number, operating system, addresses,
 * tools, last online). Opens from Devices with a client chosen; the Print button prints only the list (the rest of the console is hidden by the print style). Hidden devices are left out.
 */
import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { devicesApi, type DeviceRow } from '@/lib/api';
import { inventoryLines, kindCounts } from '@/lib/deviceInventory';

const PAGE = 200;
const MAX_PAGES = 25;

export default function PrintInventory({ today = new Date().toISOString().slice(0, 10) }: { today?: string } = {}) {
  const clientId = useSearchParams()?.get('client') ?? '';
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [problem, setProblem] = useState('');
  const [partial, setPartial] = useState(false);
  useEffect(() => {
    if (!clientId) return;
    let live = true;
    void (async () => {
      try {
        const all: DeviceRow[] = [];
        for (let page = 1; page <= MAX_PAGES; page++) {
          const r = await devicesApi.list({ clientId, page, pageSize: PAGE, presence: 'all' });
          all.push(...r.items);
          if (page >= r.pages) break;
          if (page === MAX_PAGES && live) setPartial(true);
        }
        if (live) setDevices(all);
      } catch (e) {
        if (live) setProblem(e instanceof Error && e.message ? e.message : 'Could not load the devices.');
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);

  if (!clientId) return <p className="p-6 text-sm text-gray-400">Choose a client on the Devices page, then Print inventory.</p>;
  if (problem)
    return (
      <p role="alert" className="p-6 text-sm text-red-300">
        {problem}
      </p>
    );
  if (devices === null) return <p className="p-6 text-sm text-gray-400">Loading the devices...</p>;
  const lines = inventoryLines(devices);
  const client = devices[0]?.client_name ?? 'Client';
  return (
    <div className="space-y-3 p-6 print:p-0" data-testid="print-inventory">
      <div className="flex items-start justify-between gap-3 print:hidden">
        <p className="text-sm text-gray-400">This is the inventory as it will print.</p>
        <button type="button" onClick={() => window.print()} className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500">
          Print
        </button>
      </div>
      <header className="print:text-black">
        <h1 className="text-xl font-semibold text-white print:text-black">{client}: device inventory</h1>
        <p className="text-sm text-gray-400 print:text-gray-700">
          {today} · {lines.length} device{lines.length === 1 ? '' : 's'}
          {lines.length > 0 ? ` (${kindCounts(lines)})` : ''}
        </p>
        {partial && <p className="text-xs text-amber-300 print:text-black">Only the first {PAGE * MAX_PAGES} devices are listed.</p>}
      </header>
      {lines.length === 0 ? (
        <p className="text-sm text-gray-400">This client has no devices on record.</p>
      ) : (
        <table className="w-full text-left text-xs print:text-[9pt] print:text-black" data-testid="inventory-table">
          <thead className="uppercase text-gray-500 print:text-gray-700">
            <tr>
              {['Name', 'Kind', 'Make and model', 'Serial number', 'Operating system', 'Addresses', 'Seen by', 'Last online'].map((h) => (
                <th key={h} className="border-b border-gray-700 px-2 py-1 print:border-gray-400">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-gray-200 print:text-black">
            {lines.map((l, i) => (
              <tr key={`${l.hostname}-${i}`} className="break-inside-avoid border-b border-gray-800 print:border-gray-300">
                <td className="px-2 py-1 font-medium">{l.hostname}</td>
                <td className="px-2 py-1">{l.kind}</td>
                <td className="px-2 py-1">{l.makeModel}</td>
                <td className="px-2 py-1 font-mono">{l.serial}</td>
                <td className="px-2 py-1">{l.os}</td>
                <td className="px-2 py-1">{l.addresses}</td>
                <td className="px-2 py-1">{l.tools}</td>
                <td className="px-2 py-1">{l.lastOnline}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
