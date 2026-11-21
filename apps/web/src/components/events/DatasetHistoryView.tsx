'use client';

/**
 * Data history (SIEM style storage): the datasets CORE sends (staff hours, ticket detail, invoice lines, licenses and the rest) are replaced by each new send; every version that differed is also kept. Pick a dataset,
 * see its versions newest first, and open one whole. Each version says whether it still matches the checksum saved with it.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

interface DatasetSummary {
  key: string;
  versions: number;
  first: string;
  latest: string;
}
interface VersionRow {
  id: number;
  received_at: string;
  sha256: string;
  bytes: number;
}
interface VersionFull extends VersionRow {
  key: string;
  payload: unknown;
  verified: boolean;
}

const when = (iso: string) => iso.replace('T', ' ').slice(0, 16);
const size = (n: number) => (n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : n > 1000 ? `${Math.round(n / 1000)} KB` : `${n} B`);

async function getJson<T>(url: string): Promise<T> {
  const res = await authFetch(url);
  if (res.status === 403) throw new Error('Reading the data history needs the reports permission.');
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as T;
}

export function DatasetHistoryView() {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [key, setKey] = useState('');
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [open, setOpen] = useState<VersionFull | null>(null);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    getJson<DatasetSummary[]>('/api/v1/dataset-history')
      .then(setDatasets)
      .catch((e: unknown) => setProblem(e instanceof Error ? e.message : 'Could not load'));
  }, []);

  const pick = async (k: string) => {
    setKey(k);
    setOpen(null);
    setVersions([]);
    if (!k) return;
    try {
      setVersions(await getJson<VersionRow[]>(`/api/v1/dataset-history/${encodeURIComponent(k)}`));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  };

  const show = async (v: VersionRow) => {
    if (open?.id === v.id) return setOpen(null);
    try {
      setOpen(await getJson<VersionFull>(`/api/v1/dataset-history/version/${v.id}`));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not open the version');
    }
  };

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Data history</h1>
        <a href="/events" className="text-xs text-blue-300 hover:underline">
          Event search
        </a>
        <p className="mt-1 text-sm text-gray-400">
          The data sets CORE sends are replaced by each new send. Every version that differed is kept here, never changed, so you can see what a number was on an earlier day.
        </p>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {datasets && datasets.length === 0 && !problem && (
        <p className="text-sm text-gray-400" data-testid="no-datasets">
          No version has been saved yet. One is saved each time a data set changes (at most every six hours).
        </p>
      )}
      {datasets && datasets.length > 0 && (
        <label className="flex flex-col text-xs text-gray-400">
          Data set
          <select aria-label="Data set" className="mt-1 w-72 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" value={key} onChange={(e) => void pick(e.target.value)}>
            <option value="">Choose a data set</option>
            {datasets.map((d) => (
              <option key={d.key} value={d.key}>
                {d.key} ({d.versions} versions, latest {when(d.latest)})
              </option>
            ))}
          </select>
        </label>
      )}
      {versions.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="versions-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Saved</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Checksum</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {versions.flatMap((v) => [
                <tr key={v.id} data-testid="version-row">
                  <td className="whitespace-nowrap px-3 py-1.5">
                    <button type="button" className="underline decoration-dotted hover:text-white" aria-expanded={open?.id === v.id} aria-label={`Open version ${v.id}`} onClick={() => void show(v)}>
                      {when(v.received_at)}
                    </button>
                  </td>
                  <td className="px-3 py-1.5 text-gray-400">{size(v.bytes)}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-gray-500">{v.sha256.slice(0, 12)}</td>
                </tr>,
                ...(open?.id === v.id
                  ? [
                      <tr key={`${v.id}-body`} className="bg-gray-900/50" data-testid="version-body">
                        <td colSpan={3} className="px-3 py-2">
                          <p className={open.verified ? 'mb-2 text-xs text-emerald-300' : 'mb-2 text-xs text-red-300'}>
                            {open.verified ? 'Unchanged: it still matches the checksum saved with it.' : 'This copy no longer matches the checksum saved with it.'}
                          </p>
                          <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs text-gray-300">{JSON.stringify(open.payload, null, 2)}</pre>
                        </td>
                      </tr>,
                    ]
                  : []),
              ])}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
