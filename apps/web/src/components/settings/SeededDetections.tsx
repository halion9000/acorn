'use client';

/**
 * What the platform ships, in one line on the Settings page: how many built-in detection rules there are, and how many imported Sigma rules sit in which rule packs. A person can then see what there is to
 * switch on without opening the Rules page. Read only (GET /api/v1/rules/seeded-counts); says nothing when the counts cannot be read.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';

import { authFetch } from '@/lib/auth-session';

export interface SeededCounts {
  builtin: number;
  imported: number;
  packs: { name: string; rules: number }[];
}

/** "Sigma: Windows" becomes "Windows": the packs are all Sigma, so the prefix only adds length. */
const shortName = (name: string): string => name.replace(/^Sigma:\s*/, '');

/** The sentence: built-in rules, then the imported rules and each pack, or just the built-in ones when nothing is imported. */
export function seededSentence(c: SeededCounts): string {
  const builtin = `${c.builtin.toLocaleString()} built-in rule${c.builtin === 1 ? '' : 's'}`;
  if (c.imported === 0 || c.packs.length === 0) return `${builtin}; no imported rule packs yet.`;
  const packs = c.packs.map((p) => `${shortName(p.name)} ${p.rules}`).join(', ');
  return `${builtin}; ${c.imported.toLocaleString()} imported Sigma rule${c.imported === 1 ? '' : 's'} in ${c.packs.length} rule pack${c.packs.length === 1 ? '' : 's'} (${packs}).`;
}

export function SeededDetections() {
  const [counts, setCounts] = useState<SeededCounts | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch('/api/v1/rules/seeded-counts');
        if (res.ok && live) setCounts((await res.json()) as SeededCounts);
      } catch {
        // no line: the Rules page has the full list
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  if (!counts) return null;
  return (
    <p data-testid="seeded-detections" className="mt-3 rounded-xl border border-gray-800 bg-gray-900/40 px-3 py-2 text-xs text-gray-400">
      Detections that ship with A.C.O.R.N: {seededSentence(counts)}{' '}
      <Link href="/detection" className="text-sky-300 hover:underline">
        Open Detection Rules
      </Link>
    </p>
  );
}
