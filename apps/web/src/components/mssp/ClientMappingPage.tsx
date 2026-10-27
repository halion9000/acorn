'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { msspApi, type ManagedTenantRow } from '@/lib/api';
import ClientMapping from './ClientMapping';

/** Mapping each tool's clients to your client tenants, in Settings. (It used to be a section at the bottom of the MSSP dashboard, which now only links here.) */
export default function ClientMappingPage() {
  const [tenants, setTenants] = useState<ManagedTenantRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setTenants(await msspApi.tenants(false));
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Could not load your clients.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6 p-6 max-w-7xl mx-auto">
      <div>
        <Link href="/mssp" className="text-sm text-gray-400 hover:text-gray-200">
          ← MSSP dashboard
        </Link>
        <h1 className="mt-1 text-2xl font-bold text-white">Client mapping</h1>
        <p className="text-gray-400 mt-1">Link each tool&apos;s clients to your client tenants, so alerts, devices and counts land under the right client.</p>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}{' '}
          <button type="button" onClick={() => void load()} className="underline">
            Try again
          </button>
        </p>
      ) : tenants === null ? (
        <p role="status" className="text-sm text-gray-400">
          Loading…
        </p>
      ) : (
        <ClientMapping tenants={tenants.filter((t) => !t.hidden)} onChanged={() => void load()} />
      )}
    </div>
  );
}
