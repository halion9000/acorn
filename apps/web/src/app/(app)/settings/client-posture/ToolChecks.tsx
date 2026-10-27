"use client";

import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { CHECK_HELP } from './checkHelp';

/**
 * What one tool says about the client as plain checks CORE reads once a day and sends for a client that is mapped to that tool: ThreatMate (security score, patching, end-of-life software) and
 * Liongard (disk encryption, EDR coverage, e-mail domain records, stale licensed users). Nothing is shown for a client with none (not mapped, or nothing sent yet).
 */

export interface PostureCheck {
  key: string;
  status: 'met' | 'partly' | 'not_met' | string;
  evidence: string;
  /** Since when the check has had this status, when A.C.O.R.N has seen it change. */
  since?: string | null;
  /** The accounts, machines or systems behind the verdict, when the tool says which. */
  items?: string[];
  /** Set when a person accepted this check for the client and it has not run out. */
  accepted?: { reason: string; accepted_at: string; expires_at?: string | null; not_applicable?: boolean } | null;
  /** Who is looking after the check and by when (YYYY-MM-DD); overdue once the date has passed and it is still not met. */
  owner?: string | null;
  due_date?: string | null;
  overdue?: boolean;
  /** How many comments are in the thread on this check. */
  comments?: number;
}

export interface CheckHistoryRow {
  key: string;
  source: string;
  status: string;
  previous_status: string | null;
  evidence: string;
  observed_at: string;
}

/** A check's plain name: its own title, or its key without the tool's prefix. */
export function checkTitle(key: string): string {
  return TITLE[key] ?? key.replace(/^(threatmate|liongard|itglue|fieldeffect|cipp|ninjaone|halopsa|meraki|slide|autoelevate|huntress|dnsfilter|datto)_/, '').replace(/_/g, ' ');
}

const TITLE: Record<string, string> = {
  threatmate_security_score: 'Security score',
  threatmate_patching: 'Patching',
  threatmate_end_of_life: 'End-of-life software',
  itglue_domain_expiry: 'Domain names',
  itglue_certificate_expiry: 'SSL certificates',
  threatmate_external_exposure: 'External exposure',
  threatmate_dmarc: 'DMARC and SPF',
  threatmate_hardening: 'Endpoint hardening',
  threatmate_cyber_insurance: 'Cyber insurance baseline',
  threatmate_frameworks: 'Compliance frameworks',
  liongard_disk_encryption: 'Disk encryption (BitLocker)',
  liongard_edr_coverage: 'EDR coverage',
  liongard_email_domain_records: 'E-mail domain records',
  liongard_stale_licensed_users: 'Stale licensed users',
  liongard_iis_certificates: 'Web server certificates (IIS)',
  liongard_datto_bcdr: 'Datto backup appliance',
  liongard_ad_bad_logins: 'Active Directory failed sign-ins',
  fieldeffect_account_risk: 'Account risk',
  fieldeffect_device_risk: 'Machine risk',
  cipp_inactive_accounts: 'Unused accounts',
  cipp_subscriptions: 'Microsoft 365 subscriptions',
  cipp_unused_licences: 'Unused licences',
  ninjaone_unsupported_os: 'Windows support status',
  ninjaone_antivirus: 'Antivirus',
  ninjaone_reboot: 'Restarts',
  ninjaone_disk_space: 'System drive space',
  ninjaone_patching: 'Windows updates',
  halopsa_agreement: 'Support agreement',
  meraki_licence: 'Meraki licence',
  meraki_admin_2fa: 'Meraki administrators',
  meraki_wan: 'Internet connections',
  meraki_dual_wan: 'Second internet line',
  slide_alerts: 'Backup alerts',
  slide_appliance: 'Backup appliance',
  slide_verification: 'Backup test boots',
  autoelevate_enforcing: 'Admin-rights protection',
  autoelevate_requests: 'Elevation requests',
  huntress_protection: 'Endpoint protection health',
  huntress_quiet_agents: 'Agents gone quiet',
  huntress_old_agents: 'Agents out of date',
  huntress_extra_coverage: 'Huntress identity and SIEM',
  dnsfilter_threat_blocking: 'Threat blocking (DNS)',
  dnsfilter_org_mfa: 'DNS filtering sign-in',
  dnsfilter_traffic: 'DNS filtering traffic',
  datto_saas_seats: 'Mailbox backup coverage',
  threatmate_ai_tools: 'AI tools in use',
  threatmate_pentest: 'Vulnerability scans',
  threatmate_m365_controls: 'Microsoft 365 identity controls',
  threatmate_cloud_identity: 'Cloud accounts without MFA',
};

const STATUS: Record<string, { text: string; className: string }> = {
  met: { text: 'Good', className: 'border-emerald-500/40 text-emerald-300' },
  partly: { text: 'Needs attention', className: 'border-amber-500/40 text-amber-300' },
  not_met: { text: 'Problem', className: 'border-red-500/40 text-red-300' },
};

/** A tool whose checks are older than this has probably stopped reaching A.C.O.R.N. */
export const STALE_HOURS = 48;

export function isStale(refreshedAt: string | null | undefined, now: number = Date.now()): boolean {
  if (!refreshedAt) return false;
  const t = Date.parse(refreshedAt);
  return !Number.isNaN(t) && now - t > STALE_HOURS * 3_600_000;
}

const day = (iso: string): string => new Date(iso).toLocaleDateString();

interface CheckComment {
  id: number;
  author: string;
  body: string;
  created_at: string;
}

function Comments({ clientId, check }: { clientId: string; check: string }) {
  const [rows, setRows] = useState<CheckComment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/checks/${encodeURIComponent(check)}/comments`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as { comments: CheckComment[] };
        if (live) setRows(body.comments);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : 'Could not load the comments');
      });
    return () => {
      live = false;
    };
  }, [clientId, check]);
  if (error) return <p className="mt-1 text-xs text-red-300">{error}</p>;
  if (!rows) return <p className="mt-1 text-xs text-slate-500">Loading comments…</p>;
  if (rows.length === 0) return <p className="mt-1 text-xs text-slate-500">No comments yet.</p>;
  return (
    <ul className="mt-1 space-y-1 text-xs text-slate-300" data-testid={`comments-${check}`}>
      {rows.map((c) => (
        <li key={c.id}>
          <span className="text-slate-500">
            {day(c.created_at)} {c.author}:
          </span>{' '}
          {c.body}
        </li>
      ))}
    </ul>
  );
}

function History({ clientId, check }: { clientId: string; check: string }) {
  const [rows, setRows] = useState<CheckHistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/check-history?key=${encodeURIComponent(check)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as { rows: CheckHistoryRow[] };
        if (live) setRows(body.rows);
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : 'Could not load the history');
      });
    return () => {
      live = false;
    };
  }, [clientId, check]);
  if (error) return <p className="mt-1 text-xs text-red-300">{error}</p>;
  if (!rows) return <p className="mt-1 text-xs text-slate-500">Loading history…</p>;
  if (rows.length === 0) return <p className="mt-1 text-xs text-slate-500">No history yet: A.C.O.R.N has seen this check only once.</p>;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-slate-400" data-testid={`history-${check}`}>
      {rows.map((r, i) => (
        <li key={`${r.observed_at}-${i}`}>
          {day(r.observed_at)}: {r.previous_status ? `${STATUS[r.previous_status]?.text ?? r.previous_status} → ` : 'first seen as '}
          {STATUS[r.status]?.text ?? r.status}
        </li>
      ))}
    </ul>
  );
}

export function ToolChecks({
  tool,
  label,
  checks,
  refreshedAt,
  clientId,
  onChanged,
  onlyProblems,
}: {
  tool: string;
  label: string;
  checks: PostureCheck[];
  refreshedAt?: string | null;
  /** With a client, each check can show its history and be accepted. */
  clientId?: string;
  /** Called after an acceptance is saved or removed, so the page reloads. */
  onChanged?: () => void;
  /** Hide the checks that are fine. */
  onlyProblems?: boolean;
}) {
  const [openHistory, setOpenHistory] = useState<string | null>(null);
  const [commentsOf, setCommentsOf] = useState<string | null>(null);
  const [openItems, setOpenItems] = useState<string | null>(null);
  const [openHelp, setOpenHelp] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  if (checks.length === 0) return null;
  const shown = onlyProblems ? checks.filter((c) => c.status !== 'met') : checks;
  if (shown.length === 0) return null;
  const stale = isStale(refreshedAt);

  const accept = async (key: string, notApplicable = false) => {
    if (!clientId) return;
    const reason = window.prompt(notApplicable ? 'Why does this not apply to this client? (for example: no firewall on site)' : 'Why is this accepted for this client?');
    if (!reason || reason.trim().length < 3) return;
    const body: { reason: string; expires_in_days?: number; not_applicable?: boolean } = { reason: reason.trim() };
    if (notApplicable) body.not_applicable = true;
    else {
      const days = window.prompt('For how many days? Leave empty to accept until you remove it.', '90');
      if (days && days.trim() !== '') body.expires_in_days = Number(days);
    }
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/acceptances/${encodeURIComponent(key)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      onChanged?.();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not save');
    }
  };
  const addComment = async (key: string) => {
    if (!clientId) return;
    const text = window.prompt('Comment on this check:');
    if (!text || text.trim() === '') return;
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/checks/${encodeURIComponent(key)}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: text.trim() }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      setCommentsOf(null);
      onChanged?.();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not save');
    }
  };
  const assign = async (key: string, current?: string | null) => {
    if (!clientId) return;
    const owner = window.prompt("Who is looking after this? Leave empty to clear it.", current ?? "");
    if (owner === null) return;
    const body: { owner: string; due_date?: string } = { owner: owner.trim() };
    if (owner.trim() !== "") {
      const due = window.prompt("Due date (YYYY-MM-DD)? Leave empty for none.", "");
      if (due && due.trim() !== "") {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(due.trim())) {
          setProblem("A due date looks like 2026-11-30.");
          return;
        }
        body.due_date = due.trim();
      }
    }
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/owners/${encodeURIComponent(key)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      onChanged?.();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
    }
  };
  const unaccept = async (key: string) => {
    if (!clientId) return;
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(clientId)}/acceptances/${encodeURIComponent(key)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      onChanged?.();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not remove');
    }
  };

  return (
    <section data-testid={`${tool}-checks`}>
      <h3 className="mb-2 text-sm uppercase text-slate-500">
        {label}
        {refreshedAt ? <span className="ml-2 text-xs normal-case text-slate-600">as of {new Date(refreshedAt).toLocaleDateString()}</span> : null}
        {stale ? (
          <span className="ml-2 rounded border border-amber-500/40 px-1.5 py-0.5 text-[11px] normal-case text-amber-300" data-testid={`${tool}-stale`}>
            not updated for over {STALE_HOURS} hours
          </span>
        ) : null}
      </h3>
      {problem && (
        <p role="alert" className="mb-2 text-xs text-red-300">
          {problem}
        </p>
      )}
      <div className="grid gap-2 md:grid-cols-3">
        {shown.map((c) => {
          const st = STATUS[c.status] ?? STATUS.partly;
          return (
            <div key={c.key} className={`rounded border p-2 ${c.accepted ? 'border-slate-800 opacity-80' : 'border-slate-800'}`} data-testid={`check-${c.key}`}>
              <div className="text-xs uppercase text-slate-500">{checkTitle(c.key)}</div>
              <span className={`mt-1 inline-block rounded border px-1.5 py-0.5 text-[11px] ${st.className}`}>{st.text}</span>
              {c.accepted ? (
                <span className="ml-1 inline-block rounded border border-sky-500/40 px-1.5 py-0.5 text-[11px] text-sky-300" data-testid={`accepted-${c.key}`}>
                  {c.accepted.not_applicable ? 'Not applicable' : `Accepted${c.accepted.expires_at ? ` until ${day(c.accepted.expires_at)}` : ''}`}
                </span>
              ) : null}
              {c.since ? <span className="ml-1 text-[11px] text-slate-600">since {day(c.since)}</span> : null}
              <div className="mt-1 text-xs text-slate-400">{c.evidence}</div>
              {c.accepted ? <div className="mt-1 text-xs text-sky-200/80">Reason: {c.accepted.reason}</div> : null}
              {c.owner ? (
                <div className={`mt-1 text-xs ${c.overdue ? "text-red-300" : "text-slate-400"}`} data-testid={`owner-${c.key}`}>
                  Owner: {c.owner}
                  {c.due_date ? `, due ${c.due_date}` : ""}
                  {c.overdue ? " (overdue)" : ""}
                </div>
              ) : null}
              <div className="mt-1 flex gap-3 text-[11px] print:hidden">
                {c.items && c.items.length > 0 ? (
                  <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => setOpenItems(openItems === c.key ? null : c.key)}>
                    {openItems === c.key ? 'Hide the list' : `Which ones (${c.items.length})`}
                  </button>
                ) : null}
                {CHECK_HELP[c.key] ? (
                  <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => setOpenHelp(openHelp === c.key ? null : c.key)}>
                    {openHelp === c.key ? 'Hide' : 'What this means'}
                  </button>
                ) : null}
              </div>
              {openItems === c.key && c.items ? (
                <ul className="mt-1 max-h-40 list-disc space-y-0.5 overflow-y-auto pl-4 text-xs text-slate-400" data-testid={`items-${c.key}`}>
                  {c.items.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              ) : null}
              {openHelp === c.key && CHECK_HELP[c.key] ? (
                <div className="mt-1 space-y-0.5 text-xs text-slate-400" data-testid={`help-${c.key}`}>
                  <p>{CHECK_HELP[c.key].why}</p>
                  <p className="text-slate-300">To fix: {CHECK_HELP[c.key].fix}</p>
                </div>
              ) : null}
              {clientId ? (
                <div className="mt-1 flex gap-3 text-[11px] print:hidden">
                  {c.status !== 'met' || c.owner ? (
                    <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => void assign(c.key, c.owner)}>
                      {c.owner ? 'Change owner' : 'Assign'}
                    </button>
                  ) : null}
                  <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => setCommentsOf(commentsOf === c.key ? null : c.key)}>
                    {commentsOf === c.key ? 'Hide comments' : `Comments${c.comments ? ` (${c.comments})` : ''}`}
                  </button>
                  <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => void addComment(c.key)}>
                    Add comment
                  </button>
                  <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => setOpenHistory(openHistory === c.key ? null : c.key)}>
                    {openHistory === c.key ? 'Hide history' : 'History'}
                  </button>
                  {c.accepted ? (
                    <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => void unaccept(c.key)}>
                      {c.accepted.not_applicable ? 'Applies after all' : 'Stop accepting'}
                    </button>
                  ) : c.status !== 'met' ? (
                    <>
                      <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => void accept(c.key)}>
                        Accept this
                      </button>
                      <button type="button" className="text-slate-500 underline hover:text-slate-300" onClick={() => void accept(c.key, true)}>
                        Not applicable
                      </button>
                    </>
                  ) : null}
                </div>
              ) : null}
              {clientId && openHistory === c.key ? <History clientId={clientId} check={c.key} /> : null}
              {clientId && commentsOf === c.key ? <Comments clientId={clientId} check={c.key} /> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
