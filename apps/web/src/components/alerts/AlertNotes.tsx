'use client';

import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { alertsApi, apiErrorDetail } from '@/lib/api';

/**
 * Notes on an alert: what someone looked at or who they called, written without changing the alert's status, owner or priority. A note is never edited; the newest is at the bottom.
 */
export function AlertNotes({ alertId }: { alertId: string }) {
  const { data, error, mutate } = useSWR(['alert-notes', alertId], () => alertsApi.notes(alertId), { revalidateOnFocus: false, shouldRetryOnError: false });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  const add = async () => {
    setBusy(true);
    try {
      await alertsApi.addNote(alertId, text.trim());
      setText('');
      await mutate();
    } catch (err) {
      toast.error(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : 'The note could not be saved.'));
    } finally {
      setBusy(false);
    }
  };

  if (error || !Array.isArray(data)) return null;
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-sm" data-testid="alert-notes">
      <h3 className="text-xs font-semibold uppercase text-gray-500">Notes</h3>
      {data.length === 0 ? (
        <p className="mt-1 text-gray-500" data-testid="alert-notes-empty">No notes yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {data.map((n) => (
            <li key={n.id} className="rounded border border-gray-800 p-2" data-testid="alert-note">
              <div className="text-xs text-gray-500">{n.author || 'Someone'} · {n.created_at.slice(0, 16).replace('T', ' ')} UTC</div>
              <p className="mt-0.5 whitespace-pre-wrap text-gray-200">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex gap-2">
        <textarea
          aria-label="Add a note"
          rows={2}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What you looked at, who you called…"
          className="w-full rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100"
        />
        <button type="button" disabled={busy || !text.trim()} onClick={() => void add()} className="self-start rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50">
          Add note
        </button>
      </div>
    </section>
  );
}
