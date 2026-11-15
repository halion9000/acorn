'use client';

/**
 * Vendor management for the organization or one of its clients: a Dashboard (vendors by risk level, reviews overdue), the Register (a table; open a vendor to change it, run security reviews and keep its
 * documents) and the Archive (nothing is ever deleted).
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, detectedAppsApi, vendorApi, type VendorDetail, type VendorInput, type VendorList, type VendorRow } from '@/lib/api';

type Tab = 'dashboard' | 'register' | 'archive';
const RISK_CLASS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  high: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  medium: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  unassessed: 'bg-gray-500/20 text-gray-300 border-gray-500/40',
};
export const REVIEW_LABEL: Record<VendorRow['review_state'], string> = {
  none: 'No review scheduled',
  in_progress: 'Review in progress',
  overdue: 'Review overdue',
  due: 'Review due soon',
  current: 'Up to date',
};
const REVIEW_CLASS: Record<VendorRow['review_state'], string> = {
  none: 'text-gray-500',
  in_progress: 'text-blue-300',
  overdue: 'text-red-300',
  due: 'text-amber-300',
  current: 'text-emerald-300',
};
const field = 'mt-1 block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

function RiskBadge({ level }: { level: string }) {
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-xs capitalize ${RISK_CLASS[level] ?? RISK_CLASS.unassessed}`}>{level}</span>;
}

function Dashboard({ data }: { data: VendorList }) {
  const s = data.summary;
  return (
    <div className="space-y-3" data-testid="vendor-dashboard">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {(['critical', 'high', 'medium', 'low', 'unassessed'] as const).map((l) => (
          <div key={l} className={`rounded-lg border p-3 ${RISK_CLASS[l]}`}>
            <p className="text-2xl font-semibold" data-testid={`vcount-${l}`}>
              {s.by_risk[l] ?? 0}
            </p>
            <p className="text-xs capitalize">{l}</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-gray-300">
        {s.total} vendor{s.total === 1 ? '' : 's'}; {s.reviews_in_progress} review{s.reviews_in_progress === 1 ? '' : 's'} in progress
        {s.reviews_overdue > 0 ? <span className="text-red-300"> ({s.reviews_overdue} overdue)</span> : null}.
      </p>
    </div>
  );
}

function VendorForm({ categories, initial, onSave, onCancel }: { categories: string[]; initial: Partial<VendorRow>; onSave: (v: VendorInput) => Promise<void>; onCancel: () => void }) {
  const [v, setV] = useState({
    name: initial.name ?? '',
    service: initial.service ?? '',
    category: initial.category ?? 'Other',
    owner: initial.owner ?? '',
    risk_level: initial.risk_level ?? 'unassessed',
    data_access: initial.data_access ?? 'unknown',
    website: initial.website ?? '',
    trust_url: initial.trust_url ?? '',
    auth_type: initial.auth_type ?? '',
    mfa: initial.mfa === true ? 'yes' : initial.mfa === false ? 'no' : '',
    account_manager_name: initial.account_manager_name ?? '',
    account_manager_email: initial.account_manager_email ?? '',
    contract_start: initial.contract_start ?? '',
    contract_end: initial.contract_end ?? '',
    review_interval_months: initial.review_interval_months ? String(initial.review_interval_months) : '',
    notes: initial.notes ?? '',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const text = (key: keyof typeof v, label: string, type = 'text') => (
    <label className="text-xs text-gray-400">
      {label}
      <input aria-label={label} type={type} value={v[key]} onChange={(e) => setV({ ...v, [key]: e.target.value })} className={field} />
    </label>
  );
  return (
    <form
      className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setErr('');
        const blank = (s: string) => s.trim() || null;
        try {
          await onSave({
            name: v.name.trim(),
            service: blank(v.service),
            category: v.category,
            owner: blank(v.owner),
            risk_level: v.risk_level as VendorRow['risk_level'],
            data_access: v.data_access as VendorRow['data_access'],
            website: blank(v.website),
            trust_url: blank(v.trust_url),
            auth_type: blank(v.auth_type),
            mfa: v.mfa === 'yes' ? true : v.mfa === 'no' ? false : null,
            account_manager_name: blank(v.account_manager_name),
            account_manager_email: blank(v.account_manager_email),
            contract_start: blank(v.contract_start),
            contract_end: blank(v.contract_end),
            review_interval_months: v.review_interval_months ? Number(v.review_interval_months) : null,
            clear_review_schedule: !v.review_interval_months && !!initial.review_interval_months,
            notes: v.notes,
          });
        } catch (x) {
          setErr(apiErrorDetail(x) ?? (x instanceof Error ? x.message : 'Could not save.'));
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-gray-400">
          Vendor name
          <input aria-label="Vendor name" required minLength={2} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} className={field} />
        </label>
        {text('service', 'What it provides')}
        <label className="text-xs text-gray-400">
          Category
          <select aria-label="Category" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })} className={field}>
            {categories.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        {text('owner', 'Owner')}
        <label className="text-xs text-gray-400">
          Risk level
          <select aria-label="Risk level" value={v.risk_level} onChange={(e) => setV({ ...v, risk_level: e.target.value as VendorRow['risk_level'] })} className={field}>
            {['unassessed', 'low', 'medium', 'high', 'critical'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Data it can reach
          <select aria-label="Data it can reach" value={v.data_access} onChange={(e) => setV({ ...v, data_access: e.target.value as VendorRow['data_access'] })} className={field}>
            {['unknown', 'none', 'internal', 'sensitive'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        {text('website', 'Website')}
        {text('trust_url', 'Trust center link')}
        {text('auth_type', 'How people sign in')}
        <label className="text-xs text-gray-400">
          Two-factor sign-in
          <select aria-label="Two-factor sign-in" value={v.mfa} onChange={(e) => setV({ ...v, mfa: e.target.value })} className={field}>
            <option value="">Not known</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        {text('account_manager_name', 'Account manager')}
        {text('account_manager_email', 'Account manager email', 'email')}
        {text('contract_start', 'Contract start', 'date')}
        {text('contract_end', 'Contract end', 'date')}
        <label className="text-xs text-gray-400">
          Review every (months)
          <input aria-label="Review every (months)" type="number" min={1} max={60} value={v.review_interval_months} onChange={(e) => setV({ ...v, review_interval_months: e.target.value })} className={field} />
        </label>
      </div>
      <label className="block text-xs text-gray-400">
        Notes
        <textarea aria-label="Notes" rows={3} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} className={field} />
      </label>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-50">
          Save vendor
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-300 hover:bg-gray-800">
          Cancel
        </button>
      </div>
    </form>
  );
}

function Detail({ clientId, vendor, data, onChange, onClose }: { clientId: string; vendor: VendorDetail; data: VendorList; onChange: (v: VendorDetail) => void; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [doc, setDoc] = useState({ name: '', doc_type: 'Other', url: '' });
  const [findings, setFindings] = useState('');
  const [err, setErr] = useState('');
  const archived = vendor.status === 'archived';
  const open = vendor.reviews.find((r) => r.status === 'in_progress');
  const act = async (work: () => Promise<VendorDetail>) => {
    setErr('');
    try {
      onChange(await work());
    } catch (x) {
      setErr(apiErrorDetail(x) ?? (x instanceof Error ? x.message : 'That did not work.'));
    }
  };
  return (
    <section className="space-y-4 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="vendor-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">{vendor.name}</h3>
          <p className="text-xs text-gray-400">
            {vendor.category} · {vendor.service || 'service not described'} · owner {vendor.owner || 'not set'}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>
      {err && (
        <p role="alert" className="text-xs text-red-300">
          {err}
        </p>
      )}
      {editing ? (
        <VendorForm
          categories={data.categories}
          initial={vendor}
          onCancel={() => setEditing(false)}
          onSave={async (v) => {
            onChange(await vendorApi.update(clientId, vendor.id, v));
            setEditing(false);
          }}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-4 text-sm text-gray-300">
          <RiskBadge level={vendor.risk_level} />
          <span>Data: {vendor.data_access}</span>
          <span>Two-factor: {vendor.mfa === null ? 'not known' : vendor.mfa ? 'yes' : 'no'}</span>
          {vendor.contract_end && <span>Contract ends {vendor.contract_end}</span>}
          {!archived && (
            <button type="button" onClick={() => setEditing(true)} className="text-xs text-blue-300 hover:underline">
              Edit vendor
            </button>
          )}
          <button
            type="button"
            onClick={() => void act(() => (archived ? vendorApi.restore(clientId, vendor.id) : vendorApi.archive(clientId, vendor.id)))}
            className="text-xs text-gray-400 hover:text-gray-200"
          >
            {archived ? 'Restore' : 'Archive'}
          </button>
        </div>
      )}
      <div data-testid="vendor-reviews">
        <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Security reviews</h4>
        <p className={`text-xs ${REVIEW_CLASS[vendor.review_state]}`}>
          {REVIEW_LABEL[vendor.review_state]}
          {vendor.next_review_due ? `, next ${vendor.next_review_due}` : ''}
        </p>
        <ul className="mt-1 space-y-1 text-sm text-gray-300">
          {vendor.reviews.map((r) => (
            <li key={r.id}>
              {r.title} ({r.status === 'complete' ? (r.outcome === 'concerns' ? 'concerns found' : 'no concerns') : `due ${r.due_date}${r.overdue ? ', overdue' : ''}`})
              {r.findings ? <span className="text-gray-500"> - {r.findings}</span> : null}
            </li>
          ))}
          {vendor.reviews.length === 0 && <li className="text-xs text-gray-500">No reviews yet.</li>}
        </ul>
        {!archived && !open && (
          <button type="button" onClick={() => void act(() => vendorApi.startReview(clientId, vendor.id, { kind: vendor.review_interval_months ? 'recurring' : 'one_time' }))} className="mt-2 rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
            Start a review
          </button>
        )}
        {!archived && open && (
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="text-xs text-gray-400">
              What the review found
              <input aria-label="Review findings" value={findings} onChange={(e) => setFindings(e.target.value)} className={`${field} w-72`} />
            </label>
            <button type="button" onClick={() => void act(() => vendorApi.completeReview(clientId, vendor.id, open.id, { outcome: 'no_concerns', findings }))} className="rounded bg-emerald-700 px-3 py-1 text-xs text-white hover:bg-emerald-600">
              Finish: no concerns
            </button>
            <button type="button" onClick={() => void act(() => vendorApi.completeReview(clientId, vendor.id, open.id, { outcome: 'concerns', findings }))} className="rounded bg-orange-700 px-3 py-1 text-xs text-white hover:bg-orange-600">
              Finish: concerns found
            </button>
          </div>
        )}
      </div>
      {(vendor.applications?.length ?? 0) > 0 && (
        <div data-testid="vendor-applications">
          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Applications found in Microsoft 365</h4>
          <p className="text-xs text-gray-500">
            {vendor.applications!.length} app{vendor.applications!.length === 1 ? '' : 's'}, {vendor.applications!.reduce((n, x) => n + x.accounts, 0).toLocaleString()} accounts in all
          </p>
          <ul className="mt-1 space-y-0.5 text-sm text-gray-300">
            {vendor.applications!.map((x) => (
              <li key={x.id}>
                {x.name} <span className="text-xs text-gray-500">({x.accounts.toLocaleString()} account{x.accounts === 1 ? '' : 's'}, first seen {x.first_seen.slice(0, 10)})</span>
                {x.risky ? <span className="ml-1 text-xs text-amber-300">holds a risky permission</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div data-testid="vendor-documents">
        <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Documents</h4>
        <ul className="space-y-1 text-sm text-gray-300">
          {vendor.documents.map((d) => (
            <li key={d.id} className="flex items-center gap-2">
              <span className="text-xs text-gray-500">{d.doc_type}</span>
              {d.url ? (
                <a href={d.url} target="_blank" rel="noopener noreferrer" className="text-blue-300 hover:underline">
                  {d.name}
                </a>
              ) : (
                d.name
              )}
              {!archived && (
                <button type="button" aria-label={`Remove ${d.name}`} onClick={() => void act(() => vendorApi.removeDocument(clientId, vendor.id, d.id))} className="text-xs text-gray-500 hover:text-red-300">
                  Remove
                </button>
              )}
            </li>
          ))}
          {vendor.documents.length === 0 && <li className="text-xs text-gray-500">No documents recorded.</li>}
        </ul>
        {!archived && (
          <form
            className="mt-2 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const out = await vendorApi.addDocument(clientId, vendor.id, { name: doc.name, doc_type: doc.doc_type, url: doc.url.trim() || null });
                setDoc({ name: '', doc_type: 'Other', url: '' });
                return out;
              });
            }}
          >
            <label className="text-xs text-gray-400">
              Document name
              <input aria-label="Document name" required minLength={2} value={doc.name} onChange={(e) => setDoc({ ...doc, name: e.target.value })} className={`${field} w-56`} />
            </label>
            <label className="text-xs text-gray-400">
              Type
              <select aria-label="Document type" value={doc.doc_type} onChange={(e) => setDoc({ ...doc, doc_type: e.target.value })} className={field}>
                {data.document_types.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-400">
              Link
              <input aria-label="Document link" value={doc.url} onChange={(e) => setDoc({ ...doc, url: e.target.value })} className={`${field} w-64`} placeholder="https://" />
            </label>
            <button type="submit" className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
              Add document
            </button>
          </form>
        )}
      </div>
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">History</h4>
        <ul className="space-y-0.5 text-xs text-gray-400">
          {vendor.history.map((h, i) => (
            <li key={i}>
              {h.created_at.slice(0, 10)} {h.actor || 'system'}: {h.action.replace('_', ' ')}
              {h.detail ? ` - ${h.detail}` : ''}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function VendorsView() {
  const [clientId, setClientId] = useState('');
  const [tab, setTab] = useState<Tab>('dashboard');
  const [data, setData] = useState<VendorList | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<VendorDetail | null>(null);
  const [adding, setAdding] = useState(false);
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  // How many detected applications are waiting for a decision (an older server, or nothing reported yet, shows no banner).
  useEffect(() => {
    let live = true;
    detectedAppsApi
      .list(clientId, 'new')
      .then((r) => live && setWaiting(r.counts.new))
      .catch(() => live && setWaiting(0));
    return () => {
      live = false;
    };
  }, [clientId, open]);

  const load = useCallback(async () => {
    setProblem('');
    try {
      setData(await vendorApi.list(clientId, tab === 'archive'));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the vendors.'));
    }
  }, [clientId, tab]);

  useEffect(() => {
    setData(null);
    setOpen(null);
    void load();
  }, [load]);

  const show = async (id: string) => {
    try {
      setOpen(await vendorApi.get(clientId, id));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not open the vendor.');
    }
  };
  const changed = (v: VendorDetail) => {
    setOpen(v);
    void load();
  };

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Vendors</h1>
        <p className="mt-1 text-sm text-gray-400">The third parties you depend on: what each does, who owns it, how risky it is, when it was last reviewed and the documents held. Nothing is deleted: a vendor is archived.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose vendors" />
        </div>
      </div>
      {waiting > 0 && (
        <div role="status" data-testid="detected-banner" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100">
          <span>
            <strong>
              {waiting} new application{waiting === 1 ? '' : 's'} detected.
            </strong>{' '}
            New applications have been found in the Microsoft 365 tenant. Please review and action them.
          </span>
          <a href={clientId ? `/compliance/vendors/detected?client=${encodeURIComponent(clientId)}` : '/compliance/vendors/detected'} className="text-sky-300 hover:underline">
            Detected applications
          </a>
        </div>
      )}
      <div role="tablist" className="flex gap-1 border-b border-gray-800">
        {(['dashboard', 'register', 'archive'] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm capitalize ${tab === t ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
            {t}
          </button>
        ))}
        <span className="flex-1" />
        {tab !== 'archive' && (
          <div className="pb-1">
            <button type="button" onClick={() => setAdding(true)} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
              Add vendor
            </button>
          </div>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {adding && data && (
        <VendorForm
          categories={data.categories}
          initial={{}}
          onCancel={() => setAdding(false)}
          onSave={async (v) => {
            const made = await vendorApi.create(clientId, v);
            setAdding(false);
            setOpen(made);
            await load();
          }}
        />
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && tab === 'dashboard' && <Dashboard data={data} />}
      {data && tab !== 'dashboard' && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          {data.vendors.length === 0 ? (
            <p className="p-4 text-sm text-gray-400" data-testid="vendor-empty">
              {tab === 'archive' ? 'No archived vendors.' : 'No vendors yet. Add the first one.'}
            </p>
          ) : (
            <table className="w-full text-left text-sm" data-testid="vendor-table">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Vendor</th>
                  <th className="px-3 py-2">Owner</th>
                  <th className="px-3 py-2">Risk</th>
                  <th className="px-3 py-2">Reviews</th>
                  <th className="px-3 py-2">Documents</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {data.vendors.map((v) => (
                  <tr key={v.id} className="cursor-pointer hover:bg-gray-800/40" onClick={() => void show(v.id)}>
                    <td className="px-3 py-2">
                      <button type="button" className="text-left text-blue-300 hover:underline" onClick={(e) => { e.stopPropagation(); void show(v.id); }}>
                        {v.name}
                      </button>
                      <div className="text-xs text-gray-500">
                        {v.category}
                        {v.service ? ` · ${v.service}` : ''}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-gray-300">{v.owner || '—'}</td>
                    <td className="px-3 py-2">
                      <RiskBadge level={v.risk_level} />
                    </td>
                    <td className={`px-3 py-2 text-xs ${REVIEW_CLASS[v.review_state]}`}>{REVIEW_LABEL[v.review_state]}</td>
                    <td className="px-3 py-2 text-gray-300">{v.document_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {open && data && <Detail clientId={clientId} vendor={open} data={data} onChange={changed} onClose={() => setOpen(null)} />}
    </div>
  );
}
