'use client';

/**
 * "Deploy NinjaOne" on an open device that ScreenConnect knows and NinjaOne does not: pick the kind of package, the NinjaOne organisation and location and the role, and A.C.O.R.N asks CORE to install the
 * agent through ScreenConnect and then set that role once the machine shows up in NinjaOne (NinjaOne's installer link has no role of its own). The result is read back here; the role can take a few minutes.
 */
import { useEffect, useState } from 'react';
import { apiErrorDetail, devicesApi, type ConsoleLine, type NinjaDeployOptions } from '@/lib/api';

const POLL_MS = 3000;
const PACKAGE_LABEL = { msi: 'Windows installer (MSI)', pkg: 'Mac package (PKG)' } as const;
const CLASSES: Record<'msi' | 'pkg', string[]> = { msi: ['WINDOWS_WORKSTATION', 'WINDOWS_SERVER'], pkg: ['MAC', 'MAC_SERVER'] };

/** The roles that fit a package: Windows roles for an MSI, Mac roles for a PKG (pure). */
export function rolesFor(options: NinjaDeployOptions, pkg: 'msi' | 'pkg') {
  return options.roles.filter((r) => CLASSES[pkg].includes(r.node_class));
}

export function DeployNinja({ deviceId, hostname }: { deviceId: string; hostname: string }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<NinjaDeployOptions | null>(null);
  const [pkg, setPkg] = useState<'msi' | 'pkg'>('msi');
  const [orgId, setOrgId] = useState<number | null>(null);
  const [locationId, setLocationId] = useState<number | null>(null);
  const [roleId, setRoleId] = useState<number | null>(null);
  const [line, setLine] = useState<ConsoleLine | null>(null);
  const [problem, setProblem] = useState('');
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    devicesApi
      .deployOptions(deviceId)
      .then((o) => {
        if (!live) return;
        setOptions(o);
        setPkg(o.suggested_package);
        const org = o.organizations.find((x) => x.id === o.suggested_org_id) ?? null;
        setOrgId(org?.id ?? null);
        setLocationId(org?.locations[0]?.id ?? null);
        setRoleId(null);
      })
      .catch((e) => live && setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the choices.')));
    return () => {
      live = false;
    };
  }, [open, deviceId]);

  // Read the result back while it is waiting.
  useEffect(() => {
    if (!line || (line.status !== 'pending' && line.status !== 'claimed')) return;
    const timer = setInterval(() => {
      devicesApi
        .consoleLine(line.request_id)
        .then(setLine)
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [line]);

  const roles = options ? rolesFor(options, pkg) : [];
  const org = options?.organizations.find((o) => o.id === orgId) ?? null;
  const ready = orgId !== null && locationId !== null && roleId !== null;
  const waiting = line !== null && (line.status === 'pending' || line.status === 'claimed');

  const send = async () => {
    if (!ready) return;
    setProblem('');
    try {
      setLine(await devicesApi.deployNinja(deviceId, { package: pkg, org_id: orgId!, location_id: locationId!, role_id: roleId! }));
      setConfirming(false);
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not start the install.'));
    }
  };

  const field = 'mt-1 block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
  if (!open) {
    return (
      <div className="mt-3" data-testid="deploy-ninja">
        <button type="button" onClick={(e) => { e.stopPropagation(); setOpen(true); }} className="rounded border border-sky-500/40 bg-sky-500/10 px-3 py-1 text-xs text-sky-300 hover:bg-sky-500/20">
          Deploy NinjaOne
        </button>
      </div>
    );
  }
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="deploy-ninja" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Install the NinjaOne agent on {hostname}</h3>
        <button type="button" onClick={() => setOpen(false)} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      {options?.blocked && <p className="text-sm text-amber-300">{options.blocked}</p>}
      {problem && (
        <p role="alert" className="text-xs text-red-300">
          {problem}
        </p>
      )}
      {options && !options.blocked && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-gray-400">
            Package
            <select aria-label="Package" value={pkg} onChange={(e) => { setPkg(e.target.value as 'msi' | 'pkg'); setRoleId(null); }} className={field}>
              {(Object.keys(PACKAGE_LABEL) as ('msi' | 'pkg')[]).map((p) => (
                <option key={p} value={p}>
                  {PACKAGE_LABEL[p]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-400">
            Organization
            <select
              aria-label="Organization"
              value={orgId ?? ''}
              onChange={(e) => {
                const id = e.target.value === '' ? null : Number(e.target.value);
                setOrgId(id);
                setLocationId(options.organizations.find((o) => o.id === id)?.locations[0]?.id ?? null);
              }}
              className={field}
            >
              <option value="">Choose an organization</option>
              {options.organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-400">
            Location
            <select aria-label="Location" value={locationId ?? ''} onChange={(e) => setLocationId(e.target.value === '' ? null : Number(e.target.value))} className={field}>
              {(org?.locations ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-400">
            Role
            <select aria-label="Role" value={roleId ?? ''} onChange={(e) => setRoleId(e.target.value === '' ? null : Number(e.target.value))} className={field}>
              <option value="">Choose a role</option>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {options && !options.blocked && !line && (
        <div className="space-y-2">
          <p className="text-xs text-gray-400">NinjaOne&apos;s installer link has no role of its own, so the role is set after the machine enrols (a few minutes).</p>
          {confirming ? (
            <div className="flex items-center gap-2 text-sm text-gray-200">
              <span>
                Install the agent on {hostname} as SYSTEM, for {org?.name}?
              </span>
              <button type="button" onClick={() => void send()} className="rounded bg-sky-600 px-3 py-1 text-sm text-white hover:bg-sky-500">
                Yes, install
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-300 hover:bg-gray-800">
                Cancel
              </button>
            </div>
          ) : (
            <button type="button" disabled={!ready} onClick={() => setConfirming(true)} className="rounded bg-sky-600 px-3 py-1 text-sm text-white hover:bg-sky-500 disabled:opacity-40">
              Install NinjaOne
            </button>
          )}
        </div>
      )}
      {line && (
        <div className="rounded border border-gray-800 bg-black p-3 font-mono text-xs" data-testid="deploy-result">
          {waiting && <p className="text-gray-400">Installing and waiting for the machine to enrol in NinjaOne (up to about eight minutes)...</p>}
          {line.status === 'done' && <p className="whitespace-pre-wrap text-emerald-300">{line.output}</p>}
          {line.status === 'failed' && <p className="whitespace-pre-wrap text-red-300">{line.output || 'The install failed.'}</p>}
        </div>
      )}
      {waiting && <p className="text-xs text-gray-500">{line?.command}</p>}
    </div>
  );
}
