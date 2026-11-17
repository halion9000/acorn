'use client';

/**
 * What the team has been told, above every page: each live announcement (see Settings, Announcements) as one line, an information line in blue or a warning in amber, with a Dismiss button that hides it
 * for this browser session only. The text is shown as text, never as markup. Shows nothing when there is nothing live, or when the list cannot be read.
 */
import { useEffect, useState } from 'react';
import { authFetch } from '@/lib/auth-session';

export interface LiveAnnouncement {
  id: string;
  message: string;
  tone: 'info' | 'warning' | string;
  ends_on: string | null;
}

const KEY = 'aisoc.announcements.dismissed';

function readDismissed(): string[] {
  try {
    const v = JSON.parse(window.sessionStorage.getItem(KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

/** The announcements still to show: not dismissed, with text, at most five (pure). */
export function visibleAnnouncements(all: unknown, dismissed: string[]): LiveAnnouncement[] {
  if (!Array.isArray(all)) return [];
  return all
    .filter((a): a is LiveAnnouncement => !!a && typeof a === 'object' && typeof (a as LiveAnnouncement).id === 'string' && typeof (a as LiveAnnouncement).message === 'string' && (a as LiveAnnouncement).message.trim() !== '')
    .filter((a) => !dismissed.includes(a.id))
    .slice(0, 5);
}

export function AnnouncementBanner() {
  const [all, setAll] = useState<unknown>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);
  useEffect(() => {
    setDismissed(readDismissed());
    let live = true;
    authFetch('/api/v1/announcements')
      .then(async (res) => (res.ok ? await res.json() : []))
      .catch(() => [])
      .then((v) => live && setAll(v));
    return () => {
      live = false;
    };
  }, []);
  const shown = visibleAnnouncements(all, dismissed);
  if (shown.length === 0) return null;
  const dismiss = (id: string) => {
    const next = [...dismissed, id];
    setDismissed(next);
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* the banner just comes back on the next page load */
    }
  };
  return (
    <div className="mb-4 space-y-2" data-testid="announcements">
      {shown.map((a) => (
        <div
          key={a.id}
          role="status"
          data-tone={a.tone}
          className={`flex items-start justify-between gap-3 rounded-md border px-4 py-2 text-sm ${a.tone === 'warning' ? 'border-amber-500/40 bg-amber-500/10 text-amber-100' : 'border-sky-500/40 bg-sky-500/10 text-sky-100'}`}
        >
          <p>{a.message}</p>
          <button type="button" onClick={() => dismiss(a.id)} className="shrink-0 rounded px-2 text-xs underline hover:no-underline">
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
