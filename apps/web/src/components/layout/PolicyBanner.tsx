'use client';

/**
 * A line above every page when policies are waiting for the signed-in person to accept ("You have 2 policies to read and accept"), linking to My policies. Amber when one is overdue. Shows nothing when there is
 * nothing to accept or the list cannot be read.
 */
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

export interface PolicyCounts {
  to_accept: number;
  overdue: number;
}

/** What the banner says, or null when there is nothing to say (pure). */
export function bannerText(c: PolicyCounts): string | null {
  if (!(c.to_accept > 0)) return null;
  const n = c.to_accept;
  return `You have ${n} polic${n === 1 ? 'y' : 'ies'} to read and accept${c.overdue > 0 ? `, ${c.overdue} overdue` : ''}.`;
}

export function PolicyBanner() {
  const [counts, setCounts] = useState<PolicyCounts | null>(null);
  useEffect(() => {
    let live = true;
    authFetch('/api/v1/me/policies')
      .then(async (res) => (res.ok ? await res.json() : null))
      .catch(() => null)
      .then((body: { policies?: { state?: string }[] } | null) => {
        if (!live || !body || !Array.isArray(body.policies)) return;
        const open = body.policies.filter((p) => p.state !== 'accepted');
        setCounts({ to_accept: open.length, overdue: open.filter((p) => p.state === 'overdue').length });
      });
    return () => {
      live = false;
    };
  }, []);
  const text = counts ? bannerText(counts) : null;
  if (!text || !counts) return null;
  return (
    <div
      role="status"
      data-testid="policy-banner"
      className={`mb-4 flex items-center justify-between gap-3 rounded-md border px-4 py-2 text-sm ${counts.overdue > 0 ? 'border-amber-500/40 bg-amber-500/10 text-amber-100' : 'border-sky-500/40 bg-sky-500/10 text-sky-100'}`}
    >
      <p>{text}</p>
      <Link href="/my-policies" className="shrink-0 rounded px-2 text-xs underline hover:no-underline">
        Open My policies
      </Link>
    </div>
  );
}
