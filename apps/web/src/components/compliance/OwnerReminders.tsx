'use client';

/** Under the Controls list: who has controls that still need evidence, with a message for each owner to copy (and one for the controls nobody owns). Counts the controls the page lists now. */
import { useState } from 'react';
import type { ControlRowT } from '@/lib/api';
import { ownerGroups, reminderText } from '@/lib/ownerReminders';

export function OwnerReminders({ rows, today = new Date().toISOString().slice(0, 10) }: { rows: ControlRowT[]; today?: string }) {
  const groups = ownerGroups(rows);
  const [copied, setCopied] = useState<string | null>(null);
  if (groups.length === 0) return null;
  const total = groups.reduce((n, g) => n + g.controls.length, 0);
  return (
    <details className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="owner-reminders">
      <summary className="cursor-pointer text-sm font-medium text-gray-200">
        Evidence reminders by owner: {total} control{total === 1 ? '' : 's'} need evidence, {groups.length} {groups.length === 1 ? 'owner' : 'owners'}
      </summary>
      <ul className="mt-3 space-y-3">
        {groups.map((g) => (
          <li key={g.owner || '(nobody)'} className="rounded border border-gray-800 p-3" data-testid="owner-group">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm text-gray-100">
                {g.owner || 'Nobody owns these'} <span className="text-xs text-gray-500">({g.controls.length})</span>
              </span>
              <button
                type="button"
                aria-label={`Copy the reminder for ${g.owner || 'controls nobody owns'}`}
                onClick={() => {
                  void navigator.clipboard?.writeText(reminderText(g, today)).then(() => {
                    setCopied(g.owner || '(nobody)');
                    setTimeout(() => setCopied(null), 1500);
                  });
                }}
                className="rounded border border-gray-700 px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-800"
              >
                {copied === (g.owner || '(nobody)') ? 'Copied' : 'Copy reminder'}
              </button>
            </div>
            <p className="mt-1 text-xs text-gray-400">{g.controls.map((c) => `${c.framework} ${c.control_id}`).join(', ')}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
