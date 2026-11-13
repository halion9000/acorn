'use client';

/**
 * "Merge into another device…" on a device's open row: for two lines that are one machine and that the automatic rules did not join (a tool that gives it another name, a serial one tool
 * leaves out). Search the same client, choose the device this one folds into, look at the two side by side, confirm. Every tool that reported this device now reports the chosen one and this line
 * goes away; the merge is recorded and can be undone from Possible duplicates. Two devices with different serial numbers are refused by the server, and its reason is shown.
 */
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';

import { ApiError, apiErrorDetail, devicesApi, type DeviceRow } from '@/lib/api';
import { compareRows } from './DuplicateDevices';

const tools = (d: DeviceRow): string => [...new Set(d.sources.map((s) => s.vendor))].sort().join(', ') || 'no tool';

export function MergeDeviceInto({ device, onMerged }: { device: DeviceRow; onMerged: () => void }) {
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [results, setResults] = useState<DeviceRow[]>([]);
  const [chosen, setChosen] = useState<DeviceRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  // The server refused because the two have different serial numbers (409): a person who knows they are one machine can say so.
  const [serialsDiffer, setSerialsDiffer] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (!searching || debounced.length < 2) {
      setResults([]);
      return;
    }
    let live = true;
    devicesApi
      .list({ clientId: device.tenant_id, search: debounced, pageSize: 8 })
      .then((r) => live && setResults(r.items.filter((d) => d.id !== device.id)))
      .catch(() => live && setResults([]));
    return () => {
      live = false;
    };
  }, [searching, debounced, device.tenant_id, device.id]);

  async function merge(into: DeviceRow, sameMachine = false) {
    setBusy(true);
    setProblem('');
    setSerialsDiffer(false);
    try {
      await devicesApi.mergeDuplicates(into.id, device.id, sameMachine);
      toast.success(`${device.hostname} merged into ${into.hostname}`);
      setChosen(null);
      setSearching(false);
      setQ('');
      onMerged();
    } catch (err) {
      // The server's own words ("These have different serial numbers..."), not "API 409 - /api/...".
      setProblem(apiErrorDetail(err) ?? (err instanceof ApiError ? 'That was not accepted.' : err instanceof Error ? err.message : 'That was not accepted.'));
      setSerialsDiffer(err instanceof ApiError && err.status === 409);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3" data-testid="merge-device-into" onClick={(e) => e.stopPropagation()}>
      {!searching ? (
        <button type="button" onClick={() => setSearching(true)} className="text-xs text-blue-300 hover:text-blue-200">
          Merge into another device…
        </button>
      ) : (
        <div>
          <input
            autoFocus
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name, serial or address, same client"
            aria-label="Find the device to merge into"
            className="w-full max-w-sm rounded border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-200"
          />
          <ul className="mt-1 max-w-sm space-y-0.5">
            {results.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => setChosen(r)} className="w-full rounded px-1 py-0.5 text-left text-xs text-gray-200 hover:bg-gray-800">
                  {r.hostname}
                  <span className="text-gray-500"> · {tools(r)}</span>
                  {r.serial_number ? <span className="text-gray-500"> · {r.serial_number}</span> : null}
                </button>
              </li>
            ))}
            {debounced.length >= 2 && results.length === 0 ? <li className="px-1 text-xs text-gray-500">No other device of this client matches.</li> : null}
          </ul>
          <button
            type="button"
            onClick={() => {
              setSearching(false);
              setQ('');
            }}
            className="mt-1 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        </div>
      )}

      {chosen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Merge these two devices?" className="w-full max-w-2xl rounded-lg border border-gray-700 bg-gray-900 p-5 text-left shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Merge these two devices?</h3>
            <p className="mt-2 text-sm text-gray-300">
              <strong>{device.hostname}</strong> is folded into <strong>{chosen.hostname}</strong>: every tool that reported {device.hostname} ({tools(device)}) now reports {chosen.hostname}, and the {device.hostname} line goes away. You can undo it from
              Possible duplicates.
            </p>
            <table className="mt-3 w-full text-xs" data-testid="merge-compare">
              <thead className="text-gray-500">
                <tr>
                  <th className="py-1 text-left font-normal" />
                  <th className="py-1 text-left font-normal">Merged away</th>
                  <th className="py-1 text-left font-normal">Kept</th>
                </tr>
              </thead>
              <tbody>
                {compareRows(device, chosen).map((row) => (
                  <tr key={row.label} className="border-t border-gray-800">
                    <td className="py-1 pr-3 text-gray-500">{row.label}</td>
                    <td className="py-1 pr-3 text-gray-200">{row.a}</td>
                    <td className={`py-1 ${row.same ? 'text-gray-200' : 'text-amber-300'}`}>{row.b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {problem && (
              <p role="alert" className="mt-2 text-sm text-red-300">
                {problem}
              </p>
            )}
            {serialsDiffer && (
              <p className="mt-2 text-xs text-gray-400" data-testid="same-machine-note">
                A virtual machine can carry two serial numbers (the host&apos;s in one tool, the guest&apos;s in another). If you know these are the same machine, merge anyway: the other serial is kept on the merged device, so the tools do
                not split it again. You can still undo it from Possible duplicates.
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => {
                  setChosen(null);
                  setProblem('');
                  setSerialsDiffer(false);
                }} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              {serialsDiffer ? (
                <button type="button" disabled={busy} onClick={() => void merge(chosen, true)} className="rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500">
                  {busy ? 'Merging…' : 'They are the same machine: merge anyway'}
                </button>
              ) : (
                <button type="button" disabled={busy} onClick={() => void merge(chosen)} className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
                  {busy ? 'Merging…' : 'Yes, merge'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
