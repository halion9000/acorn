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
export interface DmarcProgress {
  client_id: string;
  client_name: string;
  domains: number;
  rejecting: number;
  quarantining: number;
  monitoring: number;
  ready_to_enforce: number;
}
export interface DmarcOverview {
  days: number;
  status: DmarcStatus;
  domains: DmarcRow[];
  /** How far each client's domains have come towards enforcing. Absent from an older server. */
  progress?: DmarcProgress[];
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
export interface DmarcInsights {
  days: number;
  domain: string | null;
  emails: number;
  delivery: { passed: number; failed_delivered: number; overridden: number; quarantined: number; rejected: number };
  rates: { dmarc: number | null; dkim: number | null; spf: number | null };
  series: { day: string; total: number; dmarc_fail: number; dkim_fail: number; spf_fail: number }[];
  senders: { name: string; identified: boolean; emails: number; passed: number; failed: number; status: string }[];
  /** Absent from an older server. */
  at_risk?: { name: string; identified: boolean; emails: number; passed: number; failed: number; status: string }[];
  sending_domains: { domain: string; emails: number; passed: number; failed: number; status: string }[];
}
export interface DmarcCountries {
  days: number;
  emails: number;
  countries: { code: string; emails: number; passed: number; failed: number }[];
  unknown: number;
  not_looked_up: number;
}
export interface PostureFinding {
  status: string;
  summary: string;
  record: string | null;
  issues: string[];
}
export interface DmarcCard {
  domain: string;
  days: number;
  total: number;
  pass_rate: number | null;
  policy: string;
  posture: { domain: string; status: string; mx: string[]; mail_provider: string | null; spf: PostureFinding; dmarc: PostureFinding; dkim: PostureFinding };
  /** DNS lookups the SPF record costs through every include (the limit is 10); null with no SPF record; absent from an older server. */
  spf_lookups?: number | null;
  /** False when part of the chain could not be read, so spf_lookups is a minimum. */
  spf_lookups_complete?: boolean;
  /** The MTA-STS policy: whether senders must use an encrypted, correctly named connection. Absent from an older server. */
  mta_sts?: {
    state: 'none' | 'unreadable' | 'ok';
    mode: 'enforce' | 'testing' | 'none' | null;
    max_age: number | null;
    mx_patterns: string[];
    uncovered_mx: string[];
    issues: string[];
  } | null;
  advice: string[];
}
export interface DmarcLookalikes {
  domain: string;
  checked: number;
  found: { domain: string; kind: string; has_mail: boolean }[];
}
export interface DmarcBimi {
  domain: string;
  published: boolean;
  logo_url: string | null;
  certificate_url: string | null;
  dmarc_ready: boolean;
  certificate: { organization: string | null; not_after: string; days_left: number; valid: boolean; is_vmc: boolean } | null;
  problems: string[];
}
export interface BlocklistRow {
  list_name: string;
  status: 'listed' | 'clear' | 'refused' | 'no_answer';
  detail: string;
}
export interface DmarcBlocklists {
  domain: string;
  domain_results: BlocklistRow[];
  addresses: { ip: string; emails: number; results: BlocklistRow[] }[];
  listed: number;
  not_checked: number;
}
export interface DmarcReputation {
  domain: string;
  facts: { label: string; text: string; tone: 'good' | 'warn' | 'bad' | 'unknown' }[];
}
export interface DmarcTls {
  days: number;
  domains: { domain: string; client_id: string; matched: boolean; reports: number; success: number; failure: number; success_rate: number | null; failures: { type: string; count: number }[]; last_report: string }[];
}
export interface SetupLine {
  client_id: string;
  client_name: string;
  domain: string;
  alias: string;
  client_dmarc_rua: string;
  authorization_record_name: string;
  authorization_record_value: string;
  /** False when the domain has no mail records, so it cannot receive or send mail. Absent from an older server: treated as having mail. */
  has_mx?: boolean;
  /** What public DNS shows now: true when the client's _dmarc record names this alias, false when not seen yet, null/absent when not checked or the lookup failed. */
  rua_published?: boolean | null;
  authorization_published?: boolean | null;
}
export interface DmarcSetup {
  mailbox: string | null;
  mailbox_domain: string | null;
  lines: SetupLine[];
  /** When public DNS was last asked about these records. */
  checked_at?: string | null;
}

/** The line under a record you are asked to publish: seen in public DNS, not seen yet (DNS can lag a change by a while), or not checked. */
export function publishedLabel(published: boolean | null | undefined): { text: string; tone: string } {
  if (published === true) return { text: 'Published', tone: 'text-emerald-300' };
  if (published === false) return { text: 'Not seen in DNS yet', tone: 'text-amber-300' };
  return { text: 'Not checked', tone: 'text-gray-500' };
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

/** The Exchange Online command(s) that give the shared mailbox every alias in the list, 40 to a command so none is too long to paste. Already-present aliases are skipped by Exchange without an error. */
export function aliasScript(mailbox: string, aliases: string[]): string {
  const unique = [...new Set(aliases)].sort();
  const lines: string[] = [];
  for (let i = 0; i < unique.length; i += 40) {
    lines.push(`Set-Mailbox -Identity ${mailbox} -EmailAddresses @{add=${unique.slice(i, i + 40).map((a) => `"${a}"`).join(',')}}`);
  }
  return lines.join('\n');
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

/** The SPF lookup row: how many of the 10 DNS lookups receivers allow the record uses, once every include is counted. A minimum is labelled as one and never judged "fine". Nothing when there is no count. */
export function spfLookupRow(count: number | null | undefined, complete: boolean | undefined): [string, string, string][] {
  if (count === null || count === undefined) return [];
  const partial = complete === false;
  const tone = count > 10 ? 'missing' : partial ? 'unknown' : count >= 8 ? 'needs_work' : 'good';
  return [['SPF lookups', tone, `${partial ? 'at least ' : ''}${count} of 10${partial ? ' (part of the chain could not be read)' : count > 10 ? ': receivers treat SPF as failed' : ''}`]];
}

/** The MTA-STS row. No policy is only "needs work" for a domain that receives mail (the caller decides by passing hasMail); a policy that misses a real mail server is the one red result. Nothing when the server did not say. */
export function mtaStsRow(sts: DmarcCard['mta_sts'], hasMail: boolean): [string, string, string][] {
  if (!sts) return [];
  if (sts.state === 'none') return hasMail ? [['MTA-STS', 'needs_work', 'No policy published']] : [];
  if (sts.state === 'unreadable') return [['MTA-STS', 'unknown', 'A record exists but the policy could not be read']];
  const days = sts.max_age === null ? null : Math.round(sts.max_age / 86400);
  const age = days === null ? '' : `, remembered ${days < 1 ? 'under a day' : `${days} day${days === 1 ? '' : 's'}`}`;
  if (sts.mode === 'enforce' && sts.uncovered_mx.length > 0) return [['MTA-STS', 'missing', `Enforced but does not list ${sts.uncovered_mx[0]}: senders will refuse that server`]];
  if (sts.mode === 'enforce') return [['MTA-STS', sts.issues.length > 0 ? 'needs_work' : 'good', `Enforced${age}`]];
  if (sts.mode === 'testing') return [['MTA-STS', 'needs_work', `Testing only${age}`]];
  return [['MTA-STS', 'needs_work', sts.mode === 'none' ? 'Switched off (mode none)' : 'Policy has no readable mode']];
}

const findingTone = (status: string) => (status === 'good' ? 'text-emerald-300' : status === 'needs_work' ? 'text-amber-300' : status === 'unknown' ? 'text-gray-400' : 'text-red-300');

/** One domain's report card: what DNS says right now about its mail, SPF, DMARC and DKIM, and plain-language next steps. Left out when the server cannot produce it. */
function ReportCardView({ domain, days }: { domain: string; days: number }) {
  const { data } = useSWR<DmarcCard>(`/api/v1/dmarc/domains/${encodeURIComponent(domain)}/card?days=${days}`, fetcher, { shouldRetryOnError: false });
  if (!data) return null;
  const p = data.posture;
  const rows: [string, string, string][] = [
    ['Mail records', p.mx.length > 0 ? 'good' : 'needs_work', p.mx.length > 0 ? `${p.mail_provider ?? 'Mail server'}: ${p.mx[0]}` : 'None: this domain cannot receive mail'],
    ['SPF', p.spf.status, p.spf.summary],
    ['DMARC', p.dmarc.status, p.dmarc.summary],
    ['DKIM', p.dkim.status, p.dkim.summary],
    ...spfLookupRow(data.spf_lookups, data.spf_lookups_complete),
    ...mtaStsRow(data.mta_sts, p.mx.length > 0),
  ];
  return (
    <div data-testid="report-card" className="mt-4 rounded-lg border border-gray-800 p-3">
      <h4 className="text-sm font-medium text-gray-200">Report card</h4>
      <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm md:grid-cols-[8rem_1fr]">
        {rows.map(([label, status, text]) => (
          <div key={label} className="contents">
            <dt className="text-gray-400">{label}</dt>
            <dd data-testid={`card-${label.toLowerCase().replace(' ', '-')}`} className={findingTone(status)}>
              {text}
            </dd>
          </div>
        ))}
      </dl>
      {data.advice.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-200">
          {data.advice.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  omission: 'letter dropped',
  repetition: 'letter doubled',
  swap: 'letters swapped',
  'lookalike-character': 'look-alike character',
  hyphen: 'hyphen added',
  'other-ending': 'different ending',
};

/** Names that could pass for this domain and exist in DNS. Run on request: it is a few hundred DNS questions, and it only asks DNS (nothing connects to those sites). */
function LookalikesView({ domain }: { domain: string }) {
  const [run, setRun] = useState(false);
  const { data, error, isLoading } = useSWR<DmarcLookalikes>(run ? `/api/v1/dmarc/domains/${encodeURIComponent(domain)}/lookalikes` : null, fetcher, { shouldRetryOnError: false });
  return (
    <div data-testid="lookalikes" className="mt-4 rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-gray-200">Look-alike domains</h4>
        {!run ? (
          <button type="button" onClick={() => setRun(true)} className="rounded-lg bg-gray-800 px-3 py-1 text-xs text-gray-100 hover:bg-gray-700">
            Check for look-alikes
          </button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading ? (
        <p className="mt-2 text-sm text-gray-500">Checking… this takes a little while.</p>
      ) : data ? (
        data.found.length === 0 ? (
          <p className="mt-2 text-sm text-emerald-300">None found among {data.checked} names tried. (A registered name with no address or mail records would not show.)</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {data.found.map((l) => (
              <li key={l.domain} data-testid="lookalike-row" className="flex justify-between gap-3">
                <span className="font-mono text-gray-100">{l.domain}</span>
                <span className="text-gray-400">{KIND_LABEL[l.kind] ?? l.kind}</span>
                <span className={l.has_mail ? 'text-red-300' : 'text-amber-300'}>{l.has_mail ? 'can send mail' : 'registered'}</span>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}

/** The brand-logo (BIMI) check: is a logo published, is its certificate valid and for how long, and is DMARC strong enough for the logo to show. Run on request: it fetches the certificate named in the domain's record. */
function BimiView({ domain }: { domain: string }) {
  const [run, setRun] = useState(false);
  const { data, error, isLoading } = useSWR<DmarcBimi>(run ? `/api/v1/dmarc/domains/${encodeURIComponent(domain)}/bimi` : null, fetcher, { shouldRetryOnError: false });
  return (
    <div data-testid="bimi" className="mt-4 rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-gray-200">Brand logo (BIMI)</h4>
        {!run ? (
          <button type="button" onClick={() => setRun(true)} className="rounded-lg bg-gray-800 px-3 py-1 text-xs text-gray-100 hover:bg-gray-700">
            Check logo setup
          </button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading ? (
        <p className="mt-2 text-sm text-gray-500">Checking…</p>
      ) : data ? (
        <div className="mt-2 space-y-1 text-sm">
          <p data-testid="bimi-published" className={data.published ? 'text-emerald-300' : 'text-gray-400'}>
            {data.published ? 'A BIMI record is published.' : 'No BIMI record published (the logo does not show in mail clients).'}
          </p>
          <p data-testid="bimi-dmarc" className={data.dmarc_ready ? 'text-emerald-300' : 'text-amber-300'}>
            {data.dmarc_ready ? 'DMARC is strong enough for BIMI.' : 'DMARC is not yet strong enough for BIMI.'}
          </p>
          {data.certificate ? (
            <p data-testid="bimi-cert" className={data.certificate.valid && data.certificate.days_left > 30 ? 'text-emerald-300' : 'text-red-300'}>
              Certificate{data.certificate.organization ? ` for ${data.certificate.organization}` : ''}: {data.certificate.valid ? `valid, ${data.certificate.days_left} days left` : 'not valid now'} (ends {new Date(data.certificate.not_after).toLocaleDateString()}).
            </p>
          ) : null}
          {data.problems.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-gray-200">
              {data.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

const LIST_STATUS: Record<BlocklistRow['status'], { text: string; tone: string }> = {
  listed: { text: 'LISTED', tone: 'text-red-300' },
  clear: { text: 'not listed', tone: 'text-emerald-300' },
  refused: { text: 'list refused to answer', tone: 'text-amber-300' },
  no_answer: { text: 'no answer', tone: 'text-amber-300' },
};

/** Whether the domain and its busiest sending addresses are on public blocklists. A list that refused or did not answer is shown as that, and counted apart: it never reads as "not listed". On request. */
function BlocklistsView({ domain, days }: { domain: string; days: number }) {
  const [run, setRun] = useState(false);
  const { data, error, isLoading } = useSWR<DmarcBlocklists>(run ? `/api/v1/dmarc/domains/${encodeURIComponent(domain)}/blocklists?days=${days}` : null, fetcher, { shouldRetryOnError: false });
  const flagged = data ? [...data.domain_results.map((r) => ({ who: domain, ...r })), ...data.addresses.flatMap((a) => a.results.map((r) => ({ who: a.ip, ...r })))].filter((r) => r.status !== 'clear') : [];
  return (
    <div data-testid="blocklists" className="mt-4 rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-gray-200">Blocklists</h4>
        {!run ? (
          <button type="button" onClick={() => setRun(true)} className="rounded-lg bg-gray-800 px-3 py-1 text-xs text-gray-100 hover:bg-gray-700">
            Check blocklists
          </button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading ? (
        <p className="mt-2 text-sm text-gray-500">Checking…</p>
      ) : data ? (
        <div className="mt-2 space-y-2 text-sm">
          <p data-testid="blocklist-summary" className={data.listed > 0 ? 'text-red-300' : data.not_checked > 0 ? 'text-amber-300' : 'text-emerald-300'}>
            {data.listed > 0 ? `${data.listed} listing${data.listed === 1 ? '' : 's'} found.` : 'No listings found.'}
            {data.not_checked > 0 ? ` ${data.not_checked} check${data.not_checked === 1 ? '' : 's'} could not be completed (a list refused or did not answer), so this is not a clean result for those.` : ''}
          </p>
          <p className="text-xs text-gray-500">
            Checked the domain and {data.addresses.length} sending address{data.addresses.length === 1 ? '' : 'es'}.
          </p>
          {flagged.length > 0 ? (
            <ul className="space-y-1">
              {flagged.map((r) => (
                <li key={`${r.who}-${r.list_name}`} data-testid="blocklist-row" className="flex justify-between gap-3">
                  <span className="font-mono text-gray-100">{r.who}</span>
                  <span className="text-gray-400">{r.list_name}</span>
                  <span className={LIST_STATUS[r.status].tone}>{LIST_STATUS[r.status].text}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

const FACT_TONE: Record<DmarcReputation['facts'][number]['tone'], string> = { good: 'text-emerald-300', warn: 'text-amber-300', bad: 'text-red-300', unknown: 'text-gray-400' };

/** The facts that bear on a domain's reputation: how long it has been registered, when that ends, how its own mail behaves. No single score. Blocklists are the separate check above. On request. */
function ReputationView({ domain, days }: { domain: string; days: number }) {
  const [run, setRun] = useState(false);
  const { data, error, isLoading } = useSWR<DmarcReputation>(run ? `/api/v1/dmarc/domains/${encodeURIComponent(domain)}/reputation?days=${days}` : null, fetcher, { shouldRetryOnError: false });
  return (
    <div data-testid="reputation" className="mt-4 rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium text-gray-200">Domain reputation</h4>
        {!run ? (
          <button type="button" onClick={() => setRun(true)} className="rounded-lg bg-gray-800 px-3 py-1 text-xs text-gray-100 hover:bg-gray-700">
            Check reputation
          </button>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-300">
          {(error as Error).message}
        </p>
      ) : isLoading ? (
        <p className="mt-2 text-sm text-gray-500">Checking…</p>
      ) : data ? (
        <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm md:grid-cols-[9rem_1fr]">
          {data.facts.map((f) => (
            <div key={f.label} className="contents">
              <dt className="text-gray-400">{f.label}</dt>
              <dd data-testid={`reputation-${f.label.toLowerCase().replace(/\s+/g, '-')}`} className={FACT_TONE[f.tone]}>
                {f.text}
              </dd>
            </div>
          ))}
        </dl>
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
          <ReportCardView domain={domain} days={days} />
          <LookalikesView domain={domain} />
          <BimiView domain={domain} />
          <BlocklistsView domain={domain} days={days} />
          <ReputationView domain={domain} days={days} />
          <h4 className="mt-5 text-sm font-medium text-gray-200">Sources failing DMARC</h4>
          {data.failing_sources.length === 0 ? (
            <p className="mt-1 text-sm text-emerald-300">Nothing failed in this period.</p>
          ) : (
            <div className="overflow-x-auto">
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
            </div>
          )}
        </>
      )}
    </section>
  );
}

const DELIVERY_CARDS: { key: keyof DmarcInsights['delivery']; label: string; tone: string }[] = [
  { key: 'passed', label: 'Passed and delivered', tone: 'text-emerald-300' },
  { key: 'failed_delivered', label: 'Failed, delivered anyway', tone: 'text-amber-300' },
  { key: 'overridden', label: 'Delivered, policy overridden', tone: 'text-sky-300' },
  { key: 'quarantined', label: 'Quarantined', tone: 'text-orange-300' },
  { key: 'rejected', label: 'Rejected', tone: 'text-red-300' },
];

const statusTone = (s: string) => (s === 'passing' ? 'text-emerald-300' : s === 'failing' ? 'text-red-300' : 'text-amber-300');

/** The failure rate for each day as three lines (DMARC, DKIM, SPF), 0 to 100%. */
function RateChart({ series }: { series: DmarcInsights['series'] }) {
  const w = 600;
  const h = 120;
  const x = (i: number) => (series.length < 2 ? w / 2 : (i / (series.length - 1)) * w);
  const y = (fail: number, total: number) => h - (total ? (fail / total) * h : 0);
  const line = (pick: (p: DmarcInsights['series'][number]) => number) => series.map((p, i) => `${x(i).toFixed(1)},${y(pick(p), p.total).toFixed(1)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Failure rate per day" className="h-32 w-full rounded-lg border border-gray-800 bg-gray-950">
      <polyline points={line((p) => p.dmarc_fail)} fill="none" stroke="#f87171" strokeWidth="2" />
      <polyline points={line((p) => p.dkim_fail)} fill="none" stroke="#fbbf24" strokeWidth="2" />
      <polyline points={line((p) => p.spf_fail)} fill="none" stroke="#60a5fa" strokeWidth="2" />
    </svg>
  );
}

/** A country's name in the viewer's language; the code itself when the browser does not know it. */
export function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Where the mail was sent from, busiest first, as bars. Says plainly how much could not be placed. Hidden when there is nothing to show or the lookup is unavailable. */
function Countries({ days }: { days: number }) {
  const { data } = useSWR<DmarcCountries>(`/api/v1/dmarc/countries?days=${days}`, fetcher, { shouldRetryOnError: false });
  if (!data || data.countries.length === 0) return null;
  const top = data.countries[0].emails;
  const unplaced = data.unknown + data.not_looked_up;
  return (
    <section aria-label="Where mail was sent from" className="space-y-2">
      <h3 className="text-sm font-medium text-gray-200">Where it was sent from</h3>
      <ul className="space-y-1">
        {data.countries.slice(0, 15).map((c) => (
          <li key={c.code} data-testid="country-row" className="flex items-center gap-3 text-sm">
            <span className="w-40 shrink-0 truncate text-gray-200">{countryName(c.code)}</span>
            <span className="h-2 flex-1 rounded bg-gray-800">
              <span className="block h-2 rounded bg-blue-400" style={{ width: `${Math.max(2, Math.round((c.emails / top) * 100))}%` }} />
            </span>
            <span className="w-20 text-right text-gray-300">{c.emails.toLocaleString()}</span>
            <span className={`w-16 text-right ${c.failed > 0 ? 'text-amber-300' : 'text-emerald-300'}`}>{c.failed > 0 ? `${c.failed.toLocaleString()} failed` : 'all pass'}</span>
          </li>
        ))}
      </ul>
      {unplaced > 0 ? (
        <p data-testid="country-unplaced" className="text-xs text-gray-500">
          {unplaced.toLocaleString()} messages could not be placed in a country (private or unanswered addresses, or quieter addresses not looked up).
        </p>
      ) : null}
    </section>
  );
}

/** What happened to the mail, how often it failed, who sends it. Shown only when the server has insights and there is mail to show: a failure here never hides the table below. */
function Insights({ days }: { days: number }) {
  const { data } = useSWR<DmarcInsights>(`/api/v1/dmarc/insights?days=${days}`, fetcher, { shouldRetryOnError: false });
  if (!data || data.emails === 0) return null;
  const pct = (v: number | null) => (v === null ? '—' : `${v}%`);
  return (
    <section aria-label="Mail overview" className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {DELIVERY_CARDS.map((c) => (
          <div key={c.key} data-testid={`delivery-${c.key}`} className="rounded-lg border border-gray-800 px-3 py-2">
            <p className="text-xs text-gray-400">{c.label}</p>
            <p className={`text-xl font-semibold ${c.tone}`}>{data.delivery[c.key].toLocaleString()}</p>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <p className="text-sm text-gray-300">
          Failure rate: <span className="text-red-300">DMARC {pct(data.rates.dmarc)}</span> · <span className="text-amber-300">DKIM {pct(data.rates.dkim)}</span> · <span className="text-sky-300">SPF {pct(data.rates.spf)}</span>
        </p>
        {data.series.length > 0 ? <RateChart series={data.series} /> : null}
      </div>
      <div className="grid gap-4 md:grid-cols-2 [&>*]:min-w-0 [&>*]:overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label="Top senders">
          <thead className="text-xs text-gray-400">
            <tr>
              <th className="py-1">Top senders</th>
              <th className="py-1">Messages</th>
              <th className="py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.senders.map((s) => (
              <tr key={s.name} data-testid="sender-row" className="border-t border-gray-800">
                <td className={`py-1 ${s.identified ? 'text-gray-100' : 'font-mono text-gray-400'}`}>{s.name}</td>
                <td className="py-1 text-gray-300">{s.emails.toLocaleString()}</td>
                <td className={`py-1 ${statusTone(s.status)}`}>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="w-full text-left text-sm" aria-label="Top sending domains">
          <thead className="text-xs text-gray-400">
            <tr>
              <th className="py-1">Top sending domains</th>
              <th className="py-1">Messages</th>
              <th className="py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.sending_domains.map((d) => (
              <tr key={d.domain} data-testid="sending-domain-row" className="border-t border-gray-800">
                <td className="py-1 font-mono text-gray-200">{d.domain}</td>
                <td className="py-1 text-gray-300">{d.emails.toLocaleString()}</td>
                <td className={`py-1 ${statusTone(d.status)}`}>{d.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.at_risk && data.at_risk.length > 0 ? (
        <div data-testid="at-risk" className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3">
          <h3 className="text-sm font-medium text-amber-200">Senders at risk when the policy is enforced</h3>
          <p className="mt-1 text-xs text-gray-400">Mail from these fails DMARC today. A quarantine or reject policy would start blocking it, so fix real senders first (add them to SPF or sign with DKIM).</p>
          <ul className="mt-2 space-y-1 text-sm">
            {data.at_risk.map((s) => (
              <li key={s.name} data-testid="at-risk-row" className="flex justify-between gap-3">
                <span className={s.identified ? 'text-gray-100' : 'font-mono text-gray-400'}>{s.name}</span>
                <span className="text-amber-300">
                  {s.failed.toLocaleString()} of {s.emails.toLocaleString()} failing
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Countries days={days} />
    </section>
  );
}

/** TLS reports (TLS-RPT): how many encrypted connections to each domain's mail servers worked, and why the rest failed. Hidden when none have arrived. */
function TlsSection({ days }: { days: number }) {
  const { data } = useSWR<DmarcTls>(`/api/v1/dmarc/tls?days=${days}`, fetcher, { shouldRetryOnError: false });
  if (!data || data.domains.length === 0) return null;
  return (
    <section aria-label="TLS reports" className="space-y-2">
      <h3 className="text-sm font-medium text-gray-200">Encrypted delivery (TLS reports)</h3>
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-gray-400">
          <tr>
            <th className="py-1">Domain</th>
            <th className="py-1">Sessions</th>
            <th className="py-1">Encrypted OK</th>
            <th className="py-1">Why the rest failed</th>
          </tr>
        </thead>
        <tbody>
          {data.domains.map((d) => (
            <tr key={`${d.client_id}-${d.domain}`} data-testid="tls-row" className="border-t border-gray-800">
              <td className="py-1 font-mono text-gray-200">{d.domain}</td>
              <td className="py-1 text-gray-300">{(d.success + d.failure).toLocaleString()}</td>
              <td className={`py-1 font-medium ${rateTone(d.success_rate)}`}>{d.success_rate === null ? '—' : `${d.success_rate}%`}</td>
              <td className="py-1 text-gray-400">{d.failures.length === 0 ? '—' : d.failures.map((f) => `${f.type} (${f.count})`).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** The records that ask receivers for TLS reports: these go in each client's own DNS zone (not yours), pointing at the same alias as the DMARC reports. */
export function tlsRecordsText(lines: SetupLine[], aliasOf: (l: SetupLine) => string): string {
  return lines.map((l) => `_smtp._tls.${l.domain}\tTXT\tv=TLSRPTv1; rua=mailto:${aliasOf(l)}`).join('\n');
}

/** Per client: how many domains reject, quarantine or only monitor, and how many of the monitoring ones are ready to enforce. Clients furthest behind first. */
export function PolicyProgressPanel({ progress }: { progress: DmarcProgress[] | undefined }) {
  if (!progress || progress.length === 0) return null;
  const enforcing = progress.reduce((n, p) => n + p.rejecting + p.quarantining, 0);
  const total = progress.reduce((n, p) => n + p.domains, 0);
  const ready = progress.reduce((n, p) => n + p.ready_to_enforce, 0);
  return (
    <section aria-label="Policy progress" className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="policy-progress">
      <h3 className="text-sm font-medium text-gray-100">Policy progress</h3>
      <p className="mb-2 text-xs text-gray-500">
        {enforcing} of {total} domain{total === 1 ? '' : 's'} enforce (quarantine or reject)
        {ready > 0 ? `; ${ready} still monitoring ${ready === 1 ? 'is' : 'are'} ready to start enforcing` : ''}.
      </p>
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="py-1">Client</th>
            <th className="py-1 text-right">Domains</th>
            <th className="py-1 text-right">Reject</th>
            <th className="py-1 text-right">Quarantine</th>
            <th className="py-1 text-right">Monitoring</th>
            <th className="py-1 text-right">Ready to enforce</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {progress.map((p) => (
            <tr key={p.client_id} data-testid="policy-progress-row">
              <td className="py-1 text-gray-100">{p.client_name}</td>
              <td className="py-1 text-right tabular-nums text-gray-300">{p.domains}</td>
              <td className="py-1 text-right tabular-nums text-green-300">{p.rejecting}</td>
              <td className="py-1 text-right tabular-nums text-gray-300">{p.quarantining}</td>
              <td className="py-1 text-right tabular-nums text-gray-300">{p.monitoring}</td>
              <td className={`py-1 text-right tabular-nums ${p.ready_to_enforce > 0 ? 'font-medium text-amber-300' : 'text-gray-500'}`}>{p.ready_to_enforce}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
          <PolicyProgressPanel progress={data.progress} />
          <Insights days={days} />
          <TlsSection days={days} />
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

const CHOICES_KEY = 'dmarc-setup-choices';
const lineKey = (l: SetupLine) => `${l.client_id}:${l.domain}`;

const ALIASES_KEY = 'dmarc-setup-aliases';

/** The part of an address before the @, made safe to use: lower case, letters, digits, dot, dash and underscore only, starting with a letter or digit, at most 64 characters. */
export function cleanAliasName(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9._-]/g, '').replace(/^[^a-z0-9]+/, '').slice(0, 64);
}

/** The alias names you chose on this browser, by client (a convenience: it changes nothing on the server; the mailbox only needs the alias to exist). */
function useAliasNames(): [Record<string, string>, (next: Record<string, string>) => void] {
  const [names, setNames] = useState<Record<string, string>>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(ALIASES_KEY) ?? '{}');
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? (Object.fromEntries(Object.entries(saved).filter(([, v]) => typeof v === 'string')) as Record<string, string>) : {};
    } catch {
      return {};
    }
  });
  const update = (next: Record<string, string>) => {
    setNames(next);
    try {
      window.localStorage.setItem(ALIASES_KEY, JSON.stringify(next));
    } catch {
      /* private mode: the choice lasts until the page is closed */
    }
  };
  return [names, update];
}

/** What a domain is by default: covered, unless it has no mail records (then it is left out, because it has nothing to report). */
const onByDefault = (l: SetupLine) => l.has_mx !== false;

/** The choices made on this browser (domain key to covered or not). Only choices the person made are kept, so a domain that has since gained or lost its mail records follows the default again. A
 *  convenience: it changes nothing on the server. */
function useChoices(): [Record<string, boolean>, (next: Record<string, boolean>) => void] {
  const [choices, setChoices] = useState<Record<string, boolean>>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(CHOICES_KEY) ?? '{}');
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? (Object.fromEntries(Object.entries(saved).filter(([, v]) => typeof v === 'boolean')) as Record<string, boolean>) : {};
    } catch {
      return {};
    }
  });
  const update = (next: Record<string, boolean>) => {
    setChoices(next);
    try {
      window.localStorage.setItem(CHOICES_KEY, JSON.stringify(next));
    } catch {
      /* private mode: the choice lasts until the page is closed */
    }
  };
  return [choices, update];
}

/** The lines that are still ticked, as the DNS records for your zone (one per line, tab separated: name, type, value). */
export function dnsRecordsText(lines: SetupLine[]): string {
  return lines.map((l) => `${l.authorization_record_name}\tTXT\t${l.authorization_record_value}`).join('\n');
}

function Setup() {
  const { data, error, isLoading } = useSWR<DmarcSetup>('/api/v1/dmarc/setup', fetcher, { shouldRetryOnError: false });
  const [choices, setChoices] = useChoices();
  const [aliasNames, setAliasNames] = useAliasNames();
  const [showNoMail, setShowNoMail] = useState(false);
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
  const isOn = (l: SetupLine) => choices[lineKey(l)] ?? onByDefault(l);
  const domainOfMailbox = data.mailbox_domain ?? (data.mailbox as string).split('@')[1];
  const aliasOf = (l: SetupLine) => `${cleanAliasName(aliasNames[l.client_id] ?? l.alias.split('@')[0]) || l.alias.split('@')[0]}@${domainOfMailbox}`;
  const ruaOf = (l: SetupLine) => `rua=mailto:${aliasOf(l)}`;
  const noMail = data.lines.filter((l) => l.has_mx === false);
  const shown = showNoMail ? data.lines : data.lines.filter((l) => l.has_mx !== false);
  const included = data.lines.filter(isOn);
  const aliasCount = new Set(included.map(aliasOf)).size;
  const allOn = shown.length > 0 && shown.every(isOn);
  const someOn = shown.some(isOn);
  const toggle = (l: SetupLine) => setChoices({ ...choices, [lineKey(l)]: !isOn(l) });
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
        <p className="mt-2 text-amber-200">
          Create the aliases <strong>first</strong>: mail sent to an address that does not exist bounces, and the receivers stop reporting. Untick the domains you do not want to collect reports for; the commands below cover only the ticked ones.
        </p>
      </div>
      {data.lines.length === 0 ? (
        <p className="text-sm text-gray-400">No client domains are known yet: they come from the e-mail addresses of each client&rsquo;s people.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-300">
            <span data-testid="setup-count">
              {included.length} of {data.lines.length} domains selected ({aliasCount} alias{aliasCount === 1 ? '' : 'es'})
            </span>
            {noMail.length > 0 ? (
              <span data-testid="setup-nomail" className="text-gray-400">
                {showNoMail ? '' : `${noMail.length} domain${noMail.length === 1 ? ' is' : 's are'} hidden: no mail records (MX), so nothing to report. `}
                <button type="button" onClick={() => setShowNoMail(!showNoMail)} className="text-sky-300 hover:underline">
                  {showNoMail ? 'Hide the domains without mail' : 'Show them'}
                </button>
              </span>
            ) : null}
            <button type="button" disabled={included.length === 0} aria-label="Copy the PowerShell that creates the selected aliases" onClick={() => void navigator.clipboard?.writeText(aliasScript(data.mailbox as string, included.map(aliasOf)))} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40">
              Copy PowerShell for the aliases
            </button>
            <button type="button" disabled={included.length === 0} aria-label="Copy the DNS records for the selected domains" onClick={() => void navigator.clipboard?.writeText(dnsRecordsText(included))} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40">
              Copy DNS records
            </button>
            <button type="button" disabled={included.length === 0} aria-label="Copy the TLS report records for the selected domains" title="These go in each client's own DNS zone" onClick={() => void navigator.clipboard?.writeText(tlsRecordsText(included, aliasOf))} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40">
              Copy TLS report records
            </button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-900/60 text-xs text-gray-400">
                <tr>
                  <th className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="Include every domain"
                      checked={allOn}
                      ref={(el) => {
                        if (el) el.indeterminate = someOn && !allOn;
                      }}
                      onChange={() => setChoices({ ...choices, ...Object.fromEntries(shown.map((l) => [lineKey(l), !allOn])) })}
                    />
                  </th>
                  <th className="px-3 py-2">Client</th>
                  <th className="px-3 py-2">Domain</th>
                  <th className="px-3 py-2">Alias</th>
                  <th className="px-3 py-2">Add to the client&rsquo;s DMARC record</th>
                  <th className="px-3 py-2">Add to your DNS (TXT)</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((l) => {
                  const on = isOn(l);
                  return (
                    <tr key={lineKey(l)} data-testid="setup-row" className={`border-t border-gray-800 align-top ${on ? '' : 'opacity-50'}`}>
                      <td className="px-3 py-2">
                        <input type="checkbox" aria-label={`Include ${l.domain}`} checked={on} onChange={() => toggle(l)} />
                      </td>
                      <td className="px-3 py-2 text-gray-100">{l.client_name}</td>
                      <td className="break-all px-3 py-2 font-mono text-gray-200">
                        {l.domain}
                        {l.has_mx === false ? <span className="ml-2 rounded bg-gray-700 px-1.5 py-0.5 font-sans text-[10px] uppercase text-gray-200">no mail</span> : null}
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-0.5 font-mono text-gray-200">
                          <input
                            aria-label={`Alias for ${l.client_name}`}
                            value={aliasNames[l.client_id] ?? l.alias.split('@')[0]}
                            onChange={(e) => setAliasNames({ ...aliasNames, [l.client_id]: cleanAliasName(e.target.value) })}
                            className="w-44 rounded border border-gray-700 bg-gray-950 px-1.5 py-0.5 text-xs text-gray-100"
                          />
                          <span className="text-gray-500">@{domainOfMailbox}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span className="break-all font-mono text-gray-200">{ruaOf(l)}</span> <Copy text={ruaOf(l)} label={`Copy the DMARC record value for ${l.domain}`} />
                        <div className={`mt-1 text-[11px] ${publishedLabel(l.rua_published).tone}`} data-testid="rua-status">
                          _dmarc.{l.domain}: {publishedLabel(l.rua_published).text}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="break-all font-mono text-gray-200">{l.authorization_record_name}</div>
                        <div className="break-all font-mono text-gray-400">{l.authorization_record_value}</div>{' '}
                        <Copy text={`${l.authorization_record_name}\tTXT\t${l.authorization_record_value}`} label={`Copy the DNS record for ${l.domain}`} />
                        <div className={`mt-1 text-[11px] ${publishedLabel(l.authorization_published).tone}`} data-testid="authorization-status">
                          {publishedLabel(l.authorization_published).text}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export function DmarcView() {
  const [tab, setTab] = useState<'results' | 'setup'>('results');
  return (
    <div className="min-w-0 max-w-full space-y-5 p-6">
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
