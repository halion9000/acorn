'use client';

/** Under a risk: the controls and vendors it concerns, with a way to add and remove them. */

import { useEffect, useState } from 'react';
import { apiErrorDetail, riskRegisterApi, vendorApi, type RiskDetail, type RiskLink, type VendorRow } from '@/lib/api';

export const LINK_FRAMEWORKS: { id: string; label: string }[] = [
  { id: 'SOC2', label: 'SOC 2' },
  { id: 'ISO27001', label: 'ISO 27001' },
  { id: 'NIST-CSF', label: 'NIST CSF' },
  { id: 'PCI-DSS', label: 'PCI DSS' },
  { id: 'HIPAA', label: 'HIPAA' },
  { id: 'CIS-IG1', label: 'CIS IG1' },
];

/** How a link reads in the list (pure): a control by framework, id and title, a vendor by name. */
export function linkText(l: RiskLink): string {
  if (l.kind === 'vendor') return `Vendor: ${l.label || 'a vendor that is no longer listed'}`;
  const fw = LINK_FRAMEWORKS.find((f) => f.id === l.framework)?.label ?? l.framework ?? '';
  return `Control: ${fw} ${l.ref}${l.label ? ` ${l.label}` : ''}`;
}

export function RiskLinks({ clientId, risk, archived, onChange }: { clientId: string; risk: RiskDetail; archived: boolean; onChange: (r: RiskDetail) => void }) {
  const [kind, setKind] = useState<'control' | 'vendor'>('control');
  const [framework, setFramework] = useState('SOC2');
  const [control, setControl] = useState('');
  const [vendor, setVendor] = useState('');
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [err, setErr] = useState('');
  const links = risk.links ?? [];

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const v = await vendorApi.list(clientId);
        if (live && v?.vendors) setVendors(v.vendors);
      } catch {
        /* the picker is simply empty */
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);

  const act = async (work: () => Promise<RiskDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (e) {
      setErr(apiErrorDetail(e) ?? 'That did not work.');
    }
  };
  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

  return (
    <div data-testid="risk-links">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Controls and vendors this risk concerns</h4>
      {links.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing linked yet.</p>
      ) : (
        <ul className="space-y-1 text-sm text-gray-300">
          {links.map((l) => (
            <li key={l.id} className="flex items-center gap-2">
              <span>{linkText(l)}</span>
              {!archived && (
                <button type="button" aria-label={`Remove link: ${linkText(l)}`} onClick={() => void act(() => riskRegisterApi.removeLink(clientId, risk.id, l.id))} className="ml-auto text-xs text-gray-500 hover:text-red-300">
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {err && (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {err}
        </p>
      )}
      {!archived && (
        <form
          className="mt-2 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (kind === 'control' ? !control.trim() : !vendor) return;
            void act(() => riskRegisterApi.addLink(clientId, risk.id, kind === 'control' ? { kind, framework, ref: control.trim() } : { kind, ref: vendor }));
            setControl('');
          }}
        >
          <select aria-label="Link kind" value={kind} onChange={(e) => setKind(e.target.value as 'control' | 'vendor')} className={field}>
            <option value="control">Control</option>
            <option value="vendor">Vendor</option>
          </select>
          {kind === 'control' ? (
            <>
              <select aria-label="Framework" value={framework} onChange={(e) => setFramework(e.target.value)} className={field}>
                {LINK_FRAMEWORKS.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
              <input aria-label="Control id" placeholder="Control id, e.g. CC6.1" value={control} onChange={(e) => setControl(e.target.value)} className={`${field} w-44`} />
            </>
          ) : (
            <select aria-label="Vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} className={field}>
              <option value="">Choose a vendor</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          )}
          <button type="submit" className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-200 hover:bg-gray-800">
            Add link
          </button>
        </form>
      )}
    </div>
  );
}
