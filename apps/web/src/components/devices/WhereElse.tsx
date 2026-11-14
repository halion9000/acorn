'use client';

import { useState } from 'react';
import { apiErrorDetail, devicesApi, type DeviceElsewhere } from '@/lib/api';
import { vendorLabel } from '@/components/mssp/ClientMapping';

/** "Same serial number and name" / "Same serial number" / "Same name". */
export function matchedText(on: string[]): string {
  const serial = on.includes('serial');
  const name = on.includes('name');
  if (serial && name) return 'Same serial number and name';
  return serial ? 'Same serial number' : 'Same name';
}

/** A button on an open device: lists the other devices, under any client, with the same serial number or name, and which tools feed each. For a machine shown as missing from a tool whose record sits under another client. Read only. */
export function WhereElse({ deviceId }: { deviceId: string }) {
  const [state, setState] = useState<{ loading: boolean; error: string; data: DeviceElsewhere | null }>({ loading: false, error: '', data: null });
  const look = async () => {
    setState({ loading: true, error: '', data: null });
    try {
      setState({ loading: false, error: '', data: await devicesApi.elsewhere(deviceId) });
    } catch (e) {
      setState({ loading: false, error: apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not look.'), data: null });
    }
  };
  return (
    <div className="mt-3" data-testid="where-else">
      <button type="button" disabled={state.loading} onClick={() => void look()} className="text-xs text-blue-300 hover:underline disabled:text-gray-500">
        {state.loading ? 'Looking...' : 'Where else is this machine filed?'}
      </button>
      {state.error && (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {state.error}
        </p>
      )}
      {state.data && state.data.items.length === 0 && <p className="mt-1 text-xs text-gray-400">No other device, under any client, shares this one&apos;s serial number or name.</p>}
      {state.data && state.data.items.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-gray-300">
          {state.data.items.map((i) => (
            <li key={i.device_id}>
              <span className="text-white">{i.hostname}</span> · {i.same_client ? 'this client' : (i.client_name ?? 'another client')} · {i.tools.map((t) => vendorLabel(t)).join(', ') || 'no tool'} ·{' '}
              {matchedText(i.matched_on)}
              {i.serial_number ? ` (${i.serial_number})` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
