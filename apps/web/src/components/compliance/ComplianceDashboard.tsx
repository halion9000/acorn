'use client';

/**
 * The Compliance dashboard: what the frameworks that are turned on need, as three rings (the control tests, control health, risk levels), the action items, and the available frameworks with a switch each
 * (more than one can be on). For an organization or, with the picker, one of its clients. Control tests are Live Oak's own Secureframe (shown for the organization itself only); everything else is
 * worked out by A.C.O.R.N from the evidence held and the risk register.
 */
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import useSWR from 'swr';

import { ClientPicker, clientFromAddress, useIsHomeClient } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, complianceDashboardApi, type ComplianceDashboard } from '@/lib/api';
import { authFetch } from '@/lib/auth-session';
import { Donut } from './Donut';
import { FRAMEWORK_LIST } from './frameworkList';

const PER_PAGE = 5;
const GREEN = '#22c55e';
const AMBER = '#eab308';
const RED = '#ef4444';
const GREY = '#6b7280';

interface SecureframeTests {
  tests: { total: number; passing: number; failing: number; not_evaluated: number };
}

async function readTests(): Promise<SecureframeTests | null> {
  const res = await authFetch('/api/v1/secureframe');
  if (!res.ok) return null;
  const body = (await res.json()) as { report: SecureframeTests | null };
  return body.report;
}

function Legend({ rows }: { rows: { label: string; value: number; className: string }[] }) {
  return (
    <ul className="space-y-1.5 text-xs">
      {rows.map((r) => (
        <li key={r.label} className={`rounded px-2 py-1 ${r.className}`}>
          {r.value} {r.label}
        </li>
      ))}
    </ul>
  );
}

function Card({ title, href, children, testId }: { title: string; href?: string; children: React.ReactNode; testId: string }) {
  return (
    <section className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid={testId}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        {href ? (
          <Link href={href} aria-label={`Open ${title}`} className="rounded border border-gray-700 px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-800">
            Open
          </Link>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function ComplianceDashboard() {
  const [clientId, setClientId] = useState('');
  // The pages the cards open show the same client the dashboard is showing.
  const open = (href: string) => (clientId ? `${href}?client=${encodeURIComponent(clientId)}` : href);
  const isHome = useIsHomeClient(clientId);
  const ownView = clientId === '' || isHome;
  const [data, setData] = useState<ComplianceDashboard | null>(null);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const { data: tests } = useSWR(ownView ? 'compliance-dash-tests' : null, readTests, { revalidateOnFocus: false, shouldRetryOnError: false });

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);

  const load = useCallback(async () => {
    setProblem('');
    try {
      setData(await complianceDashboardApi.dashboard(clientId));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the dashboard.'));
    }
  }, [clientId]);

  useEffect(() => {
    setData(null);
    setPage(1);
    void load();
  }, [load]);

  const toggle = async (key: string) => {
    if (!data || busy) return;
    const next = data.enabled.includes(key) ? data.enabled.filter((k) => k !== key) : [...data.enabled, key];
    setBusy(true);
    setProblem('');
    try {
      await complianceDashboardApi.setEnabled(clientId, next);
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not change the frameworks.'));
    } finally {
      setBusy(false);
    }
  };

  const items = data?.action_items ?? [];
  const pages = Math.max(1, Math.ceil(items.length / PER_PAGE));
  const shown = items.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const h = data?.health ?? null;
  const t = tests?.tests ?? null;
  const risks = data?.risks ?? null;
  const vendors = data?.vendors ?? null;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Compliance</h1>
          <p className="mt-1 text-sm text-gray-400">Where the frameworks you turn on stand: tests, control health, risks and what needs doing.</p>
        </div>
        <div className="flex items-center gap-2">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose compliance" />
          <button type="button" onClick={() => void load()} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-200 hover:bg-gray-800">
            Refresh
          </button>
        </div>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}

      <section aria-label="Frameworks" data-testid="framework-toggles">
        <h2 className="mb-2 text-sm font-semibold text-white">Frameworks</h2>
        <p className="mb-3 text-xs text-gray-400">Turn on every framework this {clientId && !isHome ? 'client' : 'organization'} is working toward. The rings and action items add up the ones that are on.</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {FRAMEWORK_LIST.map((f) => {
            const on = data?.enabled.includes(f.key) ?? false;
            const fh = data?.by_framework.find((x) => x.framework === f.key)?.health;
            return (
              <div key={f.key} className={`flex items-start justify-between gap-3 rounded-lg border p-3 ${on ? 'border-blue-500/50 bg-blue-500/5' : 'border-gray-800 bg-gray-900/40'}`}>
                <div className="min-w-0">
                  <Link href={`/compliance/${f.id}${clientId ? `?client=${encodeURIComponent(clientId)}` : ''}`} className="text-sm font-medium text-white hover:text-blue-300">
                    {f.name}
                  </Link>
                  <p className="mt-0.5 text-xs text-gray-400">{f.description}</p>
                  {on && fh ? (
                    <p className="mt-1 text-xs text-gray-300">
                      {fh.percent_healthy ?? 0}% healthy of {fh.total} controls
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={`${f.name} on`}
                  disabled={busy || data === null}
                  onClick={() => void toggle(f.key)}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${on ? 'bg-blue-600' : 'bg-gray-700'} disabled:opacity-50`}
                >
                  <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${on ? 'left-[1.15rem]' : 'left-0.5'}`} />
                </button>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card title="Testing" testId="card-testing" href={open('/compliance/frameworks')}>
          {ownView && t ? (
            <div className="flex items-center gap-4">
              <Donut
                label={`${t.passing} of ${t.total} tests passing`}
                center={`${t.total > 0 ? Math.round((t.passing * 100) / t.total) : 0}%`}
                caption="Passing"
                parts={[
                  { value: t.failing, color: RED },
                  { value: t.not_evaluated, color: AMBER },
                  { value: t.passing, color: GREEN },
                ]}
              />
              <Legend
                rows={[
                  { label: 'Failing', value: t.failing, className: 'bg-red-500/15 text-red-300' },
                  { label: 'Not evaluated', value: t.not_evaluated, className: 'bg-amber-500/15 text-amber-300' },
                  { label: 'Passing', value: t.passing, className: 'bg-emerald-500/15 text-emerald-300' },
                ]}
              />
            </div>
          ) : (
            <p className="text-sm text-gray-400" data-testid="testing-empty">
              {ownView ? 'Secureframe has not been read yet.' : 'Control tests are not set up for this client yet.'}
            </p>
          )}
        </Card>

        <Card title="Control health" testId="card-health" href={open('/compliance/frameworks')}>
          {h ? (
            <div className="flex items-center gap-4">
              <Donut
                label={`${h.healthy} of ${h.total} controls healthy`}
                center={`${h.percent_healthy ?? 0}%`}
                caption="Healthy"
                parts={[
                  { value: h.not_tested, color: GREY },
                  { value: h.unhealthy, color: RED },
                  { value: h.at_risk, color: AMBER },
                  { value: h.healthy, color: GREEN },
                ]}
              />
              <Legend
                rows={[
                  { label: 'Not tested', value: h.not_tested, className: 'bg-gray-700/50 text-gray-300' },
                  { label: 'Unhealthy', value: h.unhealthy, className: 'bg-red-500/15 text-red-300' },
                  { label: 'At risk', value: h.at_risk, className: 'bg-amber-500/15 text-amber-300' },
                  { label: 'Healthy', value: h.healthy, className: 'bg-emerald-500/15 text-emerald-300' },
                ]}
              />
            </div>
          ) : (
            <p className="text-sm text-gray-400" data-testid="health-empty">
              {data === null ? 'Loading...' : 'Turn on a framework above to see how healthy its controls are.'}
            </p>
          )}
        </Card>

        <Card title="Risk levels" testId="card-risks" href={open('/compliance/risk-register')}>
          {risks ? (
            <div className="flex items-center gap-4">
              <Donut
                label={`${risks.total} risks`}
                center={String(risks.total)}
                caption="Total risks"
                parts={[
                  { value: risks.critical, color: RED },
                  { value: risks.high, color: '#f97316' },
                  { value: risks.medium, color: AMBER },
                  { value: risks.low, color: GREEN },
                ]}
              />
              <Legend
                rows={[
                  { label: 'Critical', value: risks.critical, className: 'bg-red-500/15 text-red-300' },
                  { label: 'High', value: risks.high, className: 'bg-orange-500/15 text-orange-300' },
                  { label: 'Medium', value: risks.medium, className: 'bg-amber-500/15 text-amber-300' },
                  { label: 'Low', value: risks.low, className: 'bg-emerald-500/15 text-emerald-300' },
                ]}
              />
            </div>
          ) : (
            <p className="text-sm text-gray-400">Loading...</p>
          )}
        </Card>
        {vendors ? (
          <Card title="Vendor risk levels" testId="card-vendors" href={open('/compliance/vendors')}>
            <div className="flex items-center gap-4">
              <Donut
                label={`${vendors.total} vendors`}
                center={String(vendors.total)}
                caption="Total vendors"
                parts={[
                  { value: vendors.critical, color: RED },
                  { value: vendors.high, color: '#f97316' },
                  { value: vendors.medium, color: AMBER },
                  { value: vendors.low, color: GREEN },
                  { value: vendors.unassessed, color: '#6b7280' },
                ]}
              />
              <Legend
                rows={[
                  { label: 'Critical', value: vendors.critical, className: 'bg-red-500/15 text-red-300' },
                  { label: 'High', value: vendors.high, className: 'bg-orange-500/15 text-orange-300' },
                  { label: 'Medium', value: vendors.medium, className: 'bg-amber-500/15 text-amber-300' },
                  { label: 'Low', value: vendors.low, className: 'bg-emerald-500/15 text-emerald-300' },
                  { label: 'Unassessed', value: vendors.unassessed, className: 'bg-gray-500/15 text-gray-300' },
                ]}
              />
            </div>
          </Card>
        ) : null}
      </div>

      <section className="rounded-xl border border-gray-800 bg-gray-900/60 p-4" data-testid="action-items">
        <h2 className="mb-3 text-sm font-semibold text-white">Action items</h2>
        {data && items.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid="action-items-empty">
            Nothing needs doing right now.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th className="px-2 py-1 font-medium">Name</th>
                <th className="px-2 py-1 font-medium">Event</th>
                <th className="px-2 py-1 font-medium">Owner</th>
                <th className="px-2 py-1 font-medium">Due date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {shown.map((a, i) => (
                <tr key={`${a.name}-${i}`}>
                  <td className="px-2 py-1.5">
                    {a.link ? (
                      <Link href={`${a.link}${clientId ? `?client=${encodeURIComponent(clientId)}` : ''}`} className="text-blue-300 hover:underline">
                        {a.name}
                      </Link>
                    ) : (
                      a.name
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-red-300">{a.event}</td>
                  <td className="px-2 py-1.5 text-gray-300">{a.owner ?? 'None'}</td>
                  <td className="px-2 py-1.5 text-gray-300">{a.due ? new Date(a.due).toISOString().slice(0, 10) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {items.length > PER_PAGE && (
          <div className="mt-3 flex items-center justify-between text-xs text-gray-400" data-testid="action-pager">
            <span>
              {(page - 1) * PER_PAGE + 1} - {Math.min(page * PER_PAGE, items.length)} of {items.length} items
            </span>
            <div className="flex gap-1">
              <button type="button" aria-label="Previous page" disabled={page === 1} onClick={() => setPage(page - 1)} className="rounded border border-gray-700 px-2 py-1 disabled:opacity-40">
                &lt;
              </button>
              <button type="button" aria-label="Next page" disabled={page === pages} onClick={() => setPage(page + 1)} className="rounded border border-gray-700 px-2 py-1 disabled:opacity-40">
                &gt;
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
