'use client';

/**
 * DMARC reports per client. Results: what mail receivers saw being sent as each client's domains (worst first), one domain's trend and the sources failing. Setup: for each client domain, the
 * address to put in its DMARC record and the one DNS line, in your own zone, that lets receivers send its reports to the shared mailbox. Read only: nothing here sends mail or changes DNS.
 */
import { useState } from 'react';
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';

export interface DmarcStatus {
  configured: boolean;
  mailbox: string | null;
  last_run_at: string | null;
  last_error: string | null;
  stored: number;
  rejected: number;
  unmatched_reports: number;
}
export interface DmarcRow {
  client_id: string;
  client_name: string;
  matched: boolean;
  domain: string;
  reports: number;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number | null;
  policy: string;
  last_report: string;
}
export interface DmarcOverview {
  days: number;
  status: DmarcStatus;
  domains: DmarcRow[];
}
export interface DmarcDetail {
  domain: string;
  days: number;
  reports: number;
  total: number;
  passed: number;
  failed: number;
  policy: string;
  series: { day: string; total: number; passed: number; failed: number }[];
  failing_sources: { ip: string; count: number; header_from: string; envelope_from: string; disposition: string }[];
}
export interface SetupLine {
  client_id: string;
  client_name: string;
  domain: string;
  alias: string;
  client_dmarc_rua: string;
  authorization_record_name: string;
  authorization_record_value: string;
}
export interface DmarcSetup {
  mailbox: string | null;
  mailbox_domain: string | null;
  lines: SetupLine[];
}

const fetcher = async <T,>(url: string): Promise<T> => {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(res.status === 403 ? 'You do not have access to DMARC reports.' : `The server answered ${res.status}.`);
  return res.json();
};

/** Pass rate colours: 98% and up is healthy, 90 to 98 needs a look, below 90 is a problem. A domain with no mail at all has no rate. */
export function rateTone(rate: number | null): string {
  if (rate === null) return 'text-gray-400';
  if (rate >= 98) return 'text-emerald-300';
  if (rate >= 90) return 'text-amber-300';
  return 'text-red-300';
}

/** How a published policy reads to a person: none watches only, quarantine and reject act on failing mail. */
export function policyLabel(policy: string): string {
  return policy === 'reject' ? 'Reject' : policy === 'quarantine' ? 'Quarantine' : 'Monitor only';
}

function ago(iso: string | null): string {
  if (!iso) return 'never';
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return mins < 2 ? 'just now' : mins < 120 ? `${mins} min ago` : mins < 2880 ? `${Math.round(mins / 60)} hours ago` : `${Math.round(mins / 1440)} days ago`;
}

function Copy({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
      className="rounded border border-gray-700 px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-800"
    >
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

function StatusStrip({ status }: { status: DmarcStatus }) {
  if (!status.configured) {
    return (
      <p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">
        The shared mailbox is not set up on the server yet, so no reports are being read. It needs the mailbox address, the managing tenant and a mail app with read access to that one mailbox.
      </p>
    );
  }
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/40 px-4 py-3 text-sm text-gray-300">
      <p>
        Reading <span className="font-mono text-gray-100">{status.mailbox}</span>. Last read {ago(status.last_run_at)}; {status.stored} report{status.stored === 1 ? '' : 's'} stored
        {status.rejected ? `, ${status.rejected} file${status.rejected === 1 ? '' : 's'} that were not reports` : ''}.
      </p>
      {status.last_error ? (
        <p role="alert" className="mt-1 text-red-300">
          The last read failed: {status.last_error}
        </p>
      ) : null}
      {status.unmatched_reports > 0 ? (
        <p className="mt-1 text-amber-200">
          {status.unmatched_reports} report{status.unmatched_reports === 1 ? '' : 's'} could not be matched to a client (nobody there uses that domain), so they are listed under &ldquo;Not matched to a client&rdquo;.
        </p>
      ) : null}
    </div>
  );
}

function Detail({ domain, days, onClose }: { domain: string; days: number; onClose: () => void }) {
  const { data, error } = useSWR<DmarcDetail>(`/api/v1/dmarc/domains/${encodeURIComponent(domain)}?days=${days}`, fetcher, { shouldRetryOnError: false });
  const max = Math.max(1, ...(data?.series.map((p) => p.total) ?? [1]));
  return (
    <section aria-label={`${domain} detail`} className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-gray-100">{domain}</h3>
        <button type="button" onClick={onClose} className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-800">
          Close
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : !data ? (
        <p className="mt-3 text-sm text-gray-500">Loading…</p>
      ) : (
        <>
          <p className="mt-1 text-sm text-gray-400">
            {data.total.toLocaleString()} messages in {data.reports} report{data.reports === 1 ? '' : 's'}; {data.passed.toLocaleString()} passed, {data.failed.toLocaleString()} failed. Policy: {policyLabel(data.policy)}.
          </p>
          <div className="mt-4 flex h-24 items-end gap-1" role="img" aria-label="Messages per day: passed and failed">
            {data.series.map((p) => (
              <div key={p.day} title={`${p.day}: ${p.passed} passed, ${p.failed} failed`} className="flex w-full max-w-6 flex-col justify-end" style={{ height: '100%' }}>
                <div className="bg-red-500/70" style={{ height: `${(p.failed / max) * 100}%` }} />
                <div className="bg-emerald-500/70" style={{ height: `${(p.passed / max) * 100}%` }} />
              </div>
            ))}
          </div>
          <h4 className="mt-5 text-sm font-medium text-gray-200">Sources failing DMARC</h4>
          {data.failing_sources.length === 0 ? (
            <p className="mt-1 text-sm text-emerald-300">Nothing failed in this period.</p>
          ) : (
            <table className="mt-2 w-full text-left text-sm">
              <thead className="text-xs text-gray-500">
                <tr>
                  <th className="py-1 pr-3">Sending address</th>
                  <th className="py-1 pr-3">Messages</th>
                  <th className="py-1 pr-3">From</th>
                  <th className="py-1 pr-3">Envelope</th>
                  <th className="py-1">Receiver did</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {data.failing_sources.map((s) => (
                  <tr key={`${s.ip}-${s.envelope_from}`} className="border-t border-gray-800">
                    <td className="py-1 pr-3 font-mono">{s.ip}</td>
                    <td className="py-1 pr-3">{s.count.toLocaleString()}</td>
                    <td className="py-1 pr-3">{s.header_from || '—'}</td>
                    <td className="py-1 pr-3">{s.envelope_from || '—'}</td>
                    <td className="py-1">{s.disposition === 'none' ? 'delivered' : s.disposition}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

function Results() {
  const [days, setDays] = useState(30);
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, isLoading } = useSWR<DmarcOverview>(`/api/v1/dmarc/overview?days=${days}`, fetcher, { shouldRetryOnError: false });
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-400">
          Period
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="ml-2 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100">
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading || !data ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <>
          <StatusStrip status={data.status} />
          {data.domains.length === 0 ? (
            <p className="rounded-lg border border-gray-800 px-4 py-6 text-sm text-gray-400">
              No reports in the last {data.days} days. Receivers send one a day per domain, starting about a day after a domain&rsquo;s DMARC record points at the shared mailbox. The Setup tab lists the line each client domain needs.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-900/60 text-xs text-gray-400">
                  <tr>
                    <th className="px-3 py-2">Client</th>
                    <th className="px-3 py-2">Domain</th>
                    <th className="px-3 py-2">Messages</th>
                    <th className="px-3 py-2">Passing</th>
                    <th className="px-3 py-2">Policy</th>
                    <th className="px-3 py-2">Last report</th>
                  </tr>
                </thead>
                <tbody>
                  {data.domains.map((d) => (
                    <tr key={`${d.client_id}-${d.domain}`} data-testid="dmarc-row" onClick={() => setOpen(d.domain)} className="cursor-pointer border-t border-gray-800 hover:bg-gray-900/40">
                      <td className={`px-3 py-2 ${d.matched ? 'text-gray-100' : 'text-amber-200'}`}>{d.client_name}</td>
                      <td className="px-3 py-2 font-mono text-gray-200">
                        <button type="button" className="hover:underline" onClick={() => setOpen(d.domain)}>
                          {d.domain}
                        </button>
                      </td>
                      <td className="px-3 py-2 text-gray-300">{d.total.toLocaleString()}</td>
                      <td className={`px-3 py-2 font-medium ${rateTone(d.pass_rate)}`}>{d.pass_rate === null ? '—' : `${d.pass_rate}%`}</td>
                      <td className="px-3 py-2 text-gray-300">{policyLabel(d.policy)}</td>
                      <td className="px-3 py-2 text-gray-400">{new Date(d.last_report).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {open ? <Detail domain={open} days={days} onClose={() => setOpen(null)} /> : null}
        </>
      )}
    </div>
  );
}

function Setup() {
  const { data, error, isLoading } = useSWR<DmarcSetup>('/api/v1/dmarc/setup', fetcher, { shouldRetryOnError: false });
  if (error) {
    return (
      <p role="alert" className="text-sm text-red-300">
        {(error as Error).message}
      </p>
    );
  }
  if (isLoading || !data) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!data.mailbox) {
    return <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">Set up the shared mailbox on the server first; the lines below are built from its address.</p>;
  }
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-800 bg-gray-950/40 px-4 py-3 text-sm text-gray-300">
        <p>For each client domain, do two things:</p>
        <ol className="mt-1 list-decimal space-y-1 pl-5">
          <li>
            In <strong>your own DNS</strong> add the TXT record shown (it lets receivers send that domain&rsquo;s reports to <span className="font-mono">{data.mailbox}</span>).
          </li>
          <li>
            In the <strong>client&rsquo;s DMARC record</strong> (the TXT at <span className="font-mono">_dmarc.&lt;domain&gt;</span>) add the <span className="font-mono">rua=</span> value to the list of report addresses, keeping the ones already there.
          </li>
        </ol>
        <p className="mt-2 text-gray-400">Every alias delivers into the one mailbox, so the alias only tells reports apart and lets you retire one client without touching the others.</p>
      </div>
      {data.lines.length === 0 ? (
        <p className="text-sm text-gray-400">No client domains are known yet: they come from the e-mail addresses of each client&rsquo;s people.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-900/60 text-xs text-gray-400">
              <tr>
                <th className="px-3 py-2">Client</th>
                <th className="px-3 py-2">Domain</th>
                <th className="px-3 py-2">Add to the client&rsquo;s DMARC record</th>
                <th className="px-3 py-2">Add to your DNS (TXT)</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={`${l.client_id}-${l.domain}`} data-testid="setup-row" className="border-t border-gray-800 align-top">
                  <td className="px-3 py-2 text-gray-100">{l.client_name}</td>
                  <td className="px-3 py-2 font-mono text-gray-200">{l.domain}</td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-gray-200">{l.client_dmarc_rua}</span> <Copy text={l.client_dmarc_rua} label={`Copy the DMARC record value for ${l.domain}`} />
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-mono text-gray-200">{l.authorization_record_name}</div>
                    <div className="font-mono text-gray-400">{l.authorization_record_value}</div>{' '}
                    <Copy text={`${l.authorization_record_name}\tTXT\t${l.authorization_record_value}`} label={`Copy the DNS record for ${l.domain}`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function DmarcView() {
  const [tab, setTab] = useState<'results' | 'setup'>('results');
  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">DMARC reports</h1>
        <p className="mt-1 text-sm text-gray-400">What mail receivers saw being sent as each client&rsquo;s domains, and whether it passed. A low pass rate means real mail is failing or someone is pretending to be the client.</p>
      </div>
      <div role="tablist" className="flex gap-1 border-b border-gray-800">
        {(['results', 'setup'] as const).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? 'border-blue-400 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'}`}
          >
            {t === 'results' ? 'Results' : 'Setup'}
          </button>
        ))}
      </div>
      {tab === 'results' ? <Results /> : <Setup />}
    </div>
  );
}
