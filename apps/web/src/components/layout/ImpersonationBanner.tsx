'use client';

import { useEffect, useState } from 'react';

import { getImpersonation, type Impersonation } from '@/lib/auth-session';
import { endImpersonation } from '@/lib/impersonation';

/** Read once per page load: starting or ending an impersonation reloads the console. */
export function useImpersonation(): Impersonation | null {
  const [value, setValue] = useState<Impersonation | null>(null);
  useEffect(() => setValue(getImpersonation()), []);
  return value;
}

/**
 * The strip across the very top of the console while an administrator is signed in as another person: who they are viewing as, who they really are, and the button that ends it.
 * Always visible and amber, so nobody mistakes one person's view for their own.
 */
export function ImpersonationBanner() {
  const imp = useImpersonation();
  const [busy, setBusy] = useState(false);
  if (!imp) return null;
  const end = async () => {
    setBusy(true);
    await endImpersonation();
    window.location.assign('/settings');
  };
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="impersonation-banner"
      className="fixed inset-x-0 top-0 z-[70] flex h-9 items-center justify-center gap-3 bg-amber-500 px-4 text-sm font-medium text-black"
    >
      <span className="truncate">
        You are viewing the console as <strong>{imp.label}</strong>, with their permissions. Everything you do is logged under your name ({imp.by}).
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={() => void end()}
        className="shrink-0 rounded-md bg-black px-3 py-0.5 text-xs font-semibold text-amber-100 hover:bg-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-black disabled:opacity-60"
      >
        {busy ? 'Ending…' : 'End impersonation'}
      </button>
    </div>
  );
}
