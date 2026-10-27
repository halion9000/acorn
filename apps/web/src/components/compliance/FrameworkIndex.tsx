'use client';

/**
 * The Compliance index: a card for each framework, with a "Whose compliance" choice above them. A client chosen here goes with every card's link (`?client=<id>`), so the framework page opens on that
 * client and not on the organisation's own evidence. The choice is also written into this page's address, so a reload or a shared link keeps it. An organisation with no clients sees no choice.
 */
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';

export interface FrameworkCard {
  id: string;
  name: string;
  description: string;
  badge: string;
}

/** The framework page's address, for one client when one is chosen. */
export function frameworkHref(frameworkId: string, clientId: string): string {
  return clientId ? `/compliance/${frameworkId}?client=${encodeURIComponent(clientId)}` : `/compliance/${frameworkId}`;
}

export function FrameworkIndex({ frameworks }: { frameworks: FrameworkCard[] }) {
  const [clientId, setClientId] = useState('');
  // A link can open on one client; read once, after the first paint so the server and browser markup agree.
  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  const choose = (id: string) => {
    setClientId(id);
    try {
      window.history.replaceState(null, '', id ? `?client=${encodeURIComponent(id)}` : window.location.pathname);
    } catch {
      // the address cannot be changed here; the choice still applies to the links below
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Compliance Frameworks</h1>
        <p className="text-gray-400 text-sm mt-1">Select a framework to view controls, collect evidence, and export reports.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={choose} label="Whose compliance" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {frameworks.map((fw) => (
          <Link
            key={fw.id}
            href={frameworkHref(fw.id, clientId)}
            className="block bg-gray-800 border border-gray-700 rounded-lg p-5 hover:border-blue-500 hover:bg-gray-750 transition-all group"
          >
            <div className="flex items-start justify-between mb-3">
              <h2 className="text-white font-semibold text-base group-hover:text-blue-400 transition-colors">{fw.name}</h2>
              <span className="ml-2 flex-shrink-0 text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">{fw.badge}</span>
            </div>
            <p className="text-gray-400 text-sm leading-relaxed">{fw.description}</p>
            <div className="mt-4 text-blue-400 text-xs font-medium group-hover:text-blue-300">View Dashboard →</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
