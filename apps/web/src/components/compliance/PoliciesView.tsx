'use client';

/**
 * Policies: the written policies and the things that must be reviewed again on a schedule, for one client at a time. The picker starts on the organization's own company and the address can name another
 * (?client=). The organization's own Secureframe policy list belongs to that company only, so it is shown for it and not for another client.
 */
import { useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress, useIsHomeClient } from '@/components/mssp/ClientPicker';
import { GovernancePanel } from './GovernancePanel';
import { SecureframeRegisters } from './SecureframeRegisters';

export function PoliciesView() {
  const [clientId, setClientId] = useState('');
  const isHome = useIsHomeClient(clientId);
  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  return (
    <div className="space-y-2 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Policies</h1>
        <p className="mt-1 text-sm text-gray-400">The written policies and the things that must be reviewed again on a schedule, with an owner and a due date. Policy text is kept in numbered versions.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose policies" />
        </div>
      </div>
      {(!clientId || isHome) && <SecureframeRegisters show="policies" />}
      <GovernancePanel clientId={clientId} />
    </div>
  );
}
