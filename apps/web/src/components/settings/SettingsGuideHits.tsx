'use client';

import Link from 'next/link';
import type { GuideHit } from '@/lib/guide-search';

/** The guide sections that contain what was typed in the Settings search, each opening the guide at that section. Nothing is drawn for no hits. */
export function SettingsGuideHits({ hits }: { hits: GuideHit[] }) {
  if (hits.length === 0) return null;
  return (
    <section aria-label="In the guide" data-testid="settings-guide-hits" className="border-t border-gray-700/70 pt-3">
      <p className="mb-1 rounded-md bg-gray-800/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-sky-300/90">In the guide</p>
      <ul className="space-y-1">
        {hits.map((h) => (
          <li key={h.id}>
            <Link href={`/settings/guide#${h.id}`} className="flex flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-800/50 hover:text-gray-100">
              <span className="font-medium">{h.title}</span>
              <span className="text-xs text-gray-500">{h.snippet}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
