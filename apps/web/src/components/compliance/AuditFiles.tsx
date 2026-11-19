'use client';

/**
 * The files an audit keeps, shown to staff (Compliance > Audits) and to the auditor (Audit portal). The two sides pass their own calls; the list, the upload box and the size rule are the same. Files are
 * kept in A.C.O.R.N, at most 10 MB each, and are always downloaded (never opened in the browser).
 */
import { useCallback, useEffect, useState } from 'react';

import { apiErrorDetail, type AuditFileRow } from '@/lib/api';
import { MAX_UPLOAD_BYTES, fileToBase64, formatSize, saveBlob } from '@/lib/fileBytes';

const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';

export interface AuditFilesProps {
  load: () => Promise<AuditFileRow[]>;
  upload: (body: { name: string; content_base64: string }) => Promise<AuditFileRow[]>;
  download: (file: AuditFileRow) => Promise<Blob>;
  /** Staff only: remove a file. */
  remove?: (file: AuditFileRow) => Promise<AuditFileRow[]>;
  /** A complete audit takes no more files. */
  locked?: boolean;
}

export function AuditFiles({ load, upload, download, remove, locked }: AuditFilesProps) {
  const [files, setFiles] = useState<AuditFileRow[] | null>(null);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const rows = await load();
        if (live) setFiles(rows);
      } catch (e) {
        if (live) setProblem(apiErrorDetail(e) ?? 'Could not load the files.');
      }
    })();
    return () => {
      live = false;
    };
  }, [load]);

  const act = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem('');
    try {
      await work();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    } finally {
      setBusy(false);
    }
  };

  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setProblem(`${file.name} is ${formatSize(file.size)}; the limit is ${formatSize(MAX_UPLOAD_BYTES)}.`);
      return;
    }
    void act(async () => setFiles(await upload({ name: file.name, content_base64: await fileToBase64(file) })));
  };

  return (
    <div className="space-y-2" data-testid="audit-files">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-200">Files</h4>
        {!locked && (
          <label className={`${btn} cursor-pointer`}>
            Add a file
            <input type="file" className="sr-only" aria-label="Add a file" disabled={busy} onChange={pick} />
          </label>
        )}
      </div>
      {locked && <p className="text-xs text-gray-500">This audit is complete and takes no more files.</p>}
      {problem && (
        <p role="alert" className="text-xs text-amber-300">
          {problem}
        </p>
      )}
      {files === null ? (
        <p className="text-xs text-gray-500">Loading…</p>
      ) : files.length === 0 ? (
        <p className="text-xs text-gray-500" data-testid="audit-files-empty">
          No files yet.
        </p>
      ) : (
        <ul className="divide-y divide-gray-800 rounded border border-gray-800 text-sm">
          {files.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 px-2 py-1.5" data-testid="audit-file">
              <span className="text-gray-200">
                {f.name}{' '}
                <span className="text-xs text-gray-500">
                  {formatSize(f.size_bytes)} · {f.by_auditor ? 'the auditor' : (f.uploaded_by ?? 'staff')} · {f.created_at.slice(0, 10)}
                </span>
              </span>
              <span className="flex gap-2">
                <button type="button" className={btn} disabled={busy} aria-label={`Download ${f.name}`} onClick={() => void act(async () => saveBlob(await download(f), f.name))}>
                  Download
                </button>
                {remove && !locked && (
                  <button type="button" className={btn} disabled={busy} aria-label={`Remove ${f.name}`} onClick={() => void act(async () => setFiles(await remove(f)))}>
                    Remove
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
