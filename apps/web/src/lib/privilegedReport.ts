/**
 * The privileged account list: every administrator with who and where they are, whether Multi-Factor covers them, and when they last signed in, riskiest first (an enabled administrator with no
 * Multi-Factor, then the longest since a sign-in). Pure over the identity rows the Identities page reads; the CSV is what an auditor or a client review wants.
 */
import type { IdentityPerson } from '@/lib/api';

export interface PrivilegedRow {
  client: string;
  email: string;
  name: string;
  enabled: string;
  mfa: string;
  signinState: string;
  daysSinceSignin: number | null;
  tools: string;
  /** Why it is near the top, in words; empty when nothing stands out. */
  flag: string;
}

const MFA_WORDS: Record<string, string> = { covered: 'covered', registered_not_required: 'registered, not required', none: 'none', unknown: 'unknown' };

function riskScore(p: IdentityPerson): number {
  let n = 0;
  if (p.enabled !== false) n += 100;
  if (p.mfa === 'none') n += 50;
  else if (p.mfa === 'registered_not_required') n += 25;
  if (p.signin_state === 'never') n += 20;
  else if (p.signin_state === 'inactive') n += 15;
  return n + Math.min(p.days_since_signin ?? 0, 999) / 1000;
}

function flagOf(p: IdentityPerson): string {
  const out: string[] = [];
  if (p.enabled !== false && p.mfa === 'none') out.push('no Multi-Factor');
  else if (p.enabled !== false && p.mfa === 'registered_not_required') out.push('Multi-Factor not required');
  if (p.enabled !== false && p.signin_state === 'never') out.push('never signed in');
  else if (p.enabled !== false && p.signin_state === 'inactive') out.push('no sign-in for 90+ days');
  if (p.enabled === false) out.push('disabled');
  return out.join('; ');
}

/** Only the administrators, in the order above (pure). */
export function privilegedRows(people: IdentityPerson[]): PrivilegedRow[] {
  return people
    .filter((p) => p.admin)
    .sort((a, b) => riskScore(b) - riskScore(a) || a.email.localeCompare(b.email))
    .map((p) => ({
      client: p.client_name ?? '',
      email: p.email,
      name: p.display_name ?? '',
      enabled: p.enabled === null ? 'unknown' : p.enabled ? 'yes' : 'no',
      mfa: MFA_WORDS[p.mfa] ?? p.mfa,
      signinState: p.signin_state ?? 'unknown',
      daysSinceSignin: p.days_since_signin ?? null,
      tools: p.tools.join(' '),
      flag: flagOf(p),
    }));
}

const field = (v: string): string => {
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

export function privilegedCsv(rows: PrivilegedRow[]): string {
  const head = ['client', 'email', 'name', 'enabled', 'multi-factor', 'sign-in', 'days since sign-in', 'tools', 'flag'];
  const lines = rows.map((r) => [r.client, r.email, r.name, r.enabled, r.mfa, r.signinState, r.daysSinceSignin === null ? '' : String(r.daysSinceSignin), r.tools, r.flag].map(field).join(','));
  return [head.join(','), ...lines].join('\r\n') + '\r\n';
}
