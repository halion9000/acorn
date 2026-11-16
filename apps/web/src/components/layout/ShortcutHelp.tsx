'use client';

/**
 * A short list of the keyboard shortcuts, opened with the question mark key from anywhere that is not a place to type. Only shortcuts that really exist are listed.
 */
import { useEffect, useState } from 'react';

export const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: 'Ctrl K  or  Cmd K', does: 'Open the command palette: go to a page or search' },
  { keys: '?', does: 'Show this list' },
  { keys: 'Esc', does: 'Close this list, a drawer or the command palette' },
];

/** True for a question mark typed on its own (not with Ctrl, Cmd or Alt) while the focus is not in a box that takes text. */
export function isHelpKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; target: unknown }): boolean {
  if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey) return false;
  const t = e.target as { tagName?: string; isContentEditable?: boolean } | null;
  const tag = (t?.tagName ?? '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return false;
  return true;
}

export function ShortcutHelp() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isHelpKey(e)) {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-white">Keyboard shortcuts</h2>
        <dl className="mt-3 space-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="flex items-start justify-between gap-4">
              <dt>
                <kbd className="rounded border border-gray-600 bg-gray-800 px-1.5 py-0.5 text-xs text-gray-200">{s.keys}</kbd>
              </dt>
              <dd className="text-right text-gray-300">{s.does}</dd>
            </div>
          ))}
        </dl>
        <button type="button" onClick={() => setOpen(false)} className="mt-4 rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
          Close
        </button>
      </div>
    </div>
  );
}
