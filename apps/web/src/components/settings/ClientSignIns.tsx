'use client';

/**
 * Settings > Client sign-ins: its own page for the sign-ins of people at your clients (the client dashboard and the read-only Compliance pages). It used to sit at the very bottom of Settings > Workspace > Members,
 * where nobody found it. Needs the permission to manage people; the server checks every action itself.
 */
import { useEffect, useState } from 'react';

import { authApi } from '@/lib/api';
import { ClientPortalUsers } from './ClientPortalUsers';

export function ClientSignIns() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    authApi
      .freshCapabilities()
      .then((caps) => setAllowed(caps.includes('manage_users')))
      .catch(() => setAllowed(false));
  }, []);
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Client sign-ins</h1>
        <p className="mt-1 text-sm text-gray-400">
          Sign-ins for people at your clients: the client dashboard (their own tickets, hours and satisfaction) or the read-only Compliance pages. Each needs an authenticator app before anything opens.
        </p>
      </div>
      {allowed === false ? <p className="text-sm text-amber-300">Managing client sign-ins needs the permission to manage people.</p> : null}
      {allowed ? <ClientPortalUsers /> : null}
    </div>
  );
}
