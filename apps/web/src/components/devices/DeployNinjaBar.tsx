'use client';

/**
 * "Deploy NinjaOne" for the machines ticked on the Devices page: one organization, location and role for all of them. Each machine is checked on its own (it needs a ScreenConnect session and no NinjaOne agent yet),
 * gets the package its own system calls for (MSI for Windows, PKG for a Mac), and is left out, with the reason, when it cannot be installed or the chosen role does not fit it (a Windows role on a Mac).
 * Each install is its own request to CORE, exactly as the one on an open device; the results are read back here.
 */
import { useEffect, useMemo, useState } from 'react';
import { apiErrorDetail, devicesApi, type ConsoleLine, type NinjaDeployOptions } from '@/lib/api';

const POLL_MS = 3000;
const CLASSES: Record<'msi' | 'pkg', string[]> = { msi: ['WINDOWS_WORKSTATION', 'WINDOWS_SERVER'], pkg: ['MAC', 'MAC_SERVER'] };

export interface BulkPlanEntry {
  id: string;
  device: string;
  package: 'msi' | 'pkg' | null;
  skip: string | null;
}

/** For each machine's own options and the chosen role: which package it gets, or why it is left out (pure). */
export function planBulk(each: NinjaDeployOptions[], roleClass: string | null): BulkPlanEntry[] {
  return each.map((o) => {
    if (o.blocked) return { id: o.device_id, device: o.device, package: null, skip: o.blocked };
    if (roleClass && !CLASSES[o.suggested_package].includes(roleClass)) {
      return { id: o.device_id, device: o.device, package: null, skip: `the chosen role is not a ${o.suggested_package === 'msi' ? 'Windows' : 'Mac'} role` };
    }
    return { id: o.device_id, device: o.device, package: o.suggested_package, skip: null };
  });
}

type Sent = { id: string; device: string; line: ConsoleLine | null; error: string | null };

export default function DeployNinjaBar({ deviceIds, onClear }: { deviceIds: string[]; onClear: () => void }) {
  const [open, setOpen] = useState(false);
  const [each, setEach] = useState<NinjaDeployOptions[] | null>(null);
  const [orgId, setOrgId] = useState<number | null>(null);
  const [locationId, setLocationId] = useState<number | null>(null);
  const [roleId, setRoleId] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState<Sent[] | null>(null);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  const first = each?.find((o) => !o.blocked) ?? each?.[0] ?? null;
  const role = first?.roles.find((r) => r.id === roleId) ?? null;
  const org = first?.organizations.find((o) => o.id === orgId) ?? null;
  const plan = useMemo(() => (each ? planBulk(each, role?.node_class ?? null) : []), [each, role]);
  const going = plan.filter((p) => p.package !== null);
  const ready = orgId !== null && locationId !== null && roleId !== null && going.length > 0;

  // Read the results back while any is waiting.
  useEffect(() => {
    if (!sent || !sent.some((s) => s.line && (s.line.status === 'pending' || s.line.status === 'claimed'))) return;
    const timer = setInterval(() => {
      sent.forEach((s) => {
        if (!s.line || (s.line.status !== 'pending' && s.line.status !== 'claimed')) return;
        devicesApi
          .consoleLine(s.line.request_id)
          .then((l) => setSent((now) => (now ? now.map((x) => (x.id === s.id ? { ...x, line: l } : x)) : now)))
          .catch(() => undefined);
      });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [sent]);

  if (deviceIds.length === 0) return null;
  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-100';

  const show = async () => {
    setOpen(true);
    setProblem('');
    setSent(null);
    setConfirming(false);
    try {
      const all = await Promise.all(deviceIds.map((id) => devicesApi.deployOptions(id)));
      setEach(all);
      const good = all.find((o) => !o.blocked) ?? all[0]!;
      const o = good.organizations.find((x) => x.id === good.suggested_org_id) ?? null;
      setOrgId(o?.id ?? null);
      setLocationId(o?.locations[0]?.id ?? null);
      setRoleId(null);
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the choices.'));
    }
  };

  const send = async () => {
    if (!ready) return;
    setBusy(true);
    setProblem('');
    const out: Sent[] = [];
    for (const p of going) {
      try {
        const line = await devicesApi.deployNinja(p.id, { package: p.package!, org_id: orgId!, location_id: locationId!, role_id: roleId! });
        out.push({ id: p.id, device: p.device, line, error: null });
      } catch (e) {
        out.push({ id: p.id, device: p.device, line: null, error: apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not start the install.') });
      }
    }
    setSent(out);
    setConfirming(false);
    setBusy(false);
  };

  return (
    <div data-testid="deploy-ninja-bar" className="rounded-lg border border-sky-500/30 bg-sky-500/5 px-4 py-2 text-xs text-gray-300">
      <div className="flex flex-wrap items-center gap-2">
        <span>{deviceIds.length} selected</span>
        {!open && (
          <button type="button" onClick={() => void show()} className="rounded border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-sky-300 hover:bg-sky-500/20">
            Deploy NinjaOne to these machines
          </button>
        )}
        {open && (
          <button type="button" onClick={() => { setOpen(false); setSent(null); }} className="ml-auto text-gray-400 hover:text-gray-200">
            Close
          </button>
        )}
      </div>
      {open && problem && (
        <p role="alert" className="mt-2 text-red-300">
          {problem}
        </p>
      )}
      {open && each && first && !sent && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-gray-400">
              Organization
              <select
                aria-label="Organization"
                value={orgId ?? ''}
                onChange={(e) => {
                  const id = e.target.value === '' ? null : Number(e.target.value);
                  setOrgId(id);
                  setLocationId(first.organizations.find((o) => o.id === id)?.locations[0]?.id ?? null);
                }}
                className={`${field} mt-1 block`}
              >
                <option value="">Choose an organization</option>
                {first.organizations.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-gray-400">
              Location
              <select aria-label="Location" value={locationId ?? ''} onChange={(e) => setLocationId(e.target.value === '' ? null : Number(e.target.value))} className={`${field} mt-1 block`}>
                {(org?.locations ?? []).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-gray-400">
              Role
              <select aria-label="Role" value={roleId ?? ''} onChange={(e) => setRoleId(e.target.value === '' ? null : Number(e.target.value))} className={`${field} mt-1 block`}>
                <option value="">Choose a role</option>
                {first.roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ul className="space-y-0.5" data-testid="bulk-plan">
            {plan.map((p) => (
              <li key={p.id} className={p.skip ? 'text-amber-300' : 'text-gray-300'}>
                {p.device}: {p.skip ? `left out, ${p.skip}` : p.package === 'msi' ? 'Windows installer' : 'Mac package'}
              </li>
            ))}
          </ul>
          <p className="text-gray-500">NinjaOne&apos;s installer link has no role of its own, so each role is set after its machine enrolls (a few minutes).</p>
          {confirming ? (
            <div className="flex items-center gap-2 text-sm text-gray-200">
              <span>
                Install the agent on {going.length} machine{going.length === 1 ? '' : 's'} as SYSTEM, for {org?.name}?
              </span>
              <button type="button" disabled={busy} onClick={() => void send()} className="rounded bg-sky-600 px-3 py-1 text-white hover:bg-sky-500 disabled:opacity-50">
                Yes, install
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="rounded border border-gray-700 px-3 py-1 text-gray-300 hover:bg-gray-800">
                Cancel
              </button>
            </div>
          ) : (
            <button type="button" disabled={!ready} onClick={() => setConfirming(true)} className="rounded bg-sky-600 px-3 py-1 text-sm text-white hover:bg-sky-500 disabled:opacity-40">
              Install NinjaOne on {going.length} machine{going.length === 1 ? '' : 's'}
            </button>
          )}
        </div>
      )}
      {open && sent && (
        <div className="mt-2 space-y-1" data-testid="bulk-results">
          {sent.map((s) => (
            <p key={s.id} className={s.error || s.line?.status === 'failed' ? 'text-red-300' : s.line?.status === 'done' ? 'text-emerald-300' : 'text-gray-300'}>
              {s.device}: {s.error ?? (s.line?.status === 'done' || s.line?.status === 'failed' ? s.line.output || s.line.status : 'installing and waiting for it to enroll in NinjaOne...')}
            </p>
          ))}
          <button type="button" onClick={onClear} className="mt-1 rounded border border-gray-700 px-2 py-1 text-gray-300 hover:bg-gray-800">
            Clear the selection
          </button>
        </div>
      )}
    </div>
  );
}
