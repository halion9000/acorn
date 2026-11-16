/**
 * What to publish in a domain's DMARC record next, and what to fix first, worked out from the reports A.C.O.R.N has read. Pure: it only turns the numbers the page already holds into words.
 * The rule is the usual careful rollout: watch (p=none) until enough mail has been seen and almost all of it passes, then quarantine a small share, then reject. A domain is never moved on while
 * real mail is still failing.
 */

export type DmarcPolicy = 'none' | 'quarantine' | 'reject';

/** Mail seen (messages) before a policy is judged at all. */
export const MIN_MESSAGES = 100;
/** The share of failing mail (percent) above which a domain stays where it is. */
export const MAX_FAIL_PERCENT = 2;
/** A domain must have this many messages and a failure share below {@link TIGHT_FAIL_PERCENT} before reject is suggested. */
export const MIN_MESSAGES_FOR_REJECT = 500;
export const TIGHT_FAIL_PERCENT = 1;
/** The share of mail a first step into an enforcing policy applies to. */
export const FIRST_PCT = 10;

export function normalizePolicy(value: string | null | undefined): DmarcPolicy {
  const v = (value ?? '').trim().toLowerCase();
  return v === 'reject' ? 'reject' : v === 'quarantine' ? 'quarantine' : 'none';
}

export interface RecordParts {
  policy: DmarcPolicy;
  /** Percent of mail the policy applies to (1 to 100); 100 is left out of the record as it is the default. */
  pct?: number;
  /** The reporting address, as ``rua=mailto:name@example.com`` or just the mailto target. */
  rua?: string | null;
}

/** The text of the TXT record at _dmarc.<domain> (pure). Tags are separated by "; " in the order receivers expect, v first and p second. */
export function buildDmarcRecord(parts: RecordParts): string {
  const out = ['v=DMARC1', `p=${parts.policy}`];
  const pct = parts.pct === undefined ? 100 : Math.max(1, Math.min(100, Math.round(parts.pct)));
  if (pct < 100) out.push(`pct=${pct}`);
  const rua = (parts.rua ?? '').trim().replace(/^rua=/i, '');
  if (rua) out.push(`rua=${rua.startsWith('mailto:') ? rua : `mailto:${rua}`}`);
  return out.join('; ');
}

export interface Rollup {
  policy: string;
  total: number;
  passed: number;
  failed: number;
}

export interface NextStep {
  /** What to publish now; the same as today's when the domain should stay where it is. */
  policy: DmarcPolicy;
  pct: number;
  /** True when this is a change from today's policy or share. */
  change: boolean;
  headline: string;
  reasons: string[];
}

const pctText = (n: number): string => `${Math.round(n * 10) / 10}%`;

export function nextStep(r: Rollup): NextStep {
  const policy = normalizePolicy(r.policy);
  const failPct = r.total > 0 ? (r.failed / r.total) * 100 : 0;
  const stay = (headline: string, reasons: string[]): NextStep => ({ policy, pct: 100, change: false, headline, reasons });
  if (policy === 'reject') return stay('Already rejecting failing mail', ['Nothing to change. Keep watching the sources below for a real sender that starts to fail.']);
  if (r.total < MIN_MESSAGES) return stay('Keep watching for now', [`Only ${r.total.toLocaleString()} message${r.total === 1 ? '' : 's'} seen; at least ${MIN_MESSAGES} are needed to judge whether it is safe to enforce.`]);
  if (failPct > MAX_FAIL_PERCENT) {
    return stay('Fix the failing senders first', [`${pctText(failPct)} of ${r.total.toLocaleString()} messages fail DMARC (more than ${MAX_FAIL_PERCENT}%). A stricter policy would start blocking them.`, 'Add each real sender to SPF or turn on DKIM signing for it (see the list below), then look again.']);
  }
  if (policy === 'none') {
    return { policy: 'quarantine', pct: FIRST_PCT, change: true, headline: `Move to quarantine for ${FIRST_PCT}% of mail`, reasons: [`${pctText(failPct)} of ${r.total.toLocaleString()} messages fail, which is within ${MAX_FAIL_PERCENT}%.`, `Start with pct=${FIRST_PCT}, so a sender that was missed only loses a tenth of its mail to the spam folder, then raise the share a step at a time.`] };
  }
  if (r.total >= MIN_MESSAGES_FOR_REJECT && failPct < TIGHT_FAIL_PERCENT) {
    return { policy: 'reject', pct: FIRST_PCT, change: true, headline: `Move to reject for ${FIRST_PCT}% of mail`, reasons: [`${pctText(failPct)} of ${r.total.toLocaleString()} messages fail, which is under ${TIGHT_FAIL_PERCENT}%.`, `Start with pct=${FIRST_PCT} and raise it a step at a time.`] };
  }
  return stay('Stay on quarantine', [r.total < MIN_MESSAGES_FOR_REJECT ? `${r.total.toLocaleString()} messages seen; ${MIN_MESSAGES_FOR_REJECT} are needed before reject is suggested.` : `${pctText(failPct)} of mail still fails; it needs to be under ${TIGHT_FAIL_PERCENT}% before reject is suggested.`]);
}

export interface FailingSource {
  ip: string;
  count: number;
  header_from: string;
  envelope_from: string;
  disposition: string;
}

export interface FixItem {
  /** What to do, first thing first. */
  text: string;
  messages: number;
  /** Percent of all failing messages (0 to 100). */
  share: number;
}

export const FIXES_LISTED = 5;

/** The senders to fix first: failing sources grouped by who they say they are and the return path they use, biggest first (pure). */
export function fixList(sources: FailingSource[]): FixItem[] {
  const total = sources.reduce((n, s) => n + s.count, 0);
  const groups = new Map<string, { from: string; env: string; ips: Set<string>; count: number; blocked: number }>();
  for (const s of sources) {
    const from = s.header_from.trim().toLowerCase();
    const env = s.envelope_from.trim().toLowerCase();
    const key = `${from}|${env}`;
    const g = groups.get(key) ?? { from, env, ips: new Set<string>(), count: 0, blocked: 0 };
    g.ips.add(s.ip);
    g.count += s.count;
    if (s.disposition !== 'none') g.blocked += s.count;
    groups.set(key, g);
  }
  return [...groups.values()]
    .sort((a, b) => b.count - a.count || a.from.localeCompare(b.from))
    .slice(0, FIXES_LISTED)
    .map((g) => {
      const who = g.from ? `mail that says it is from ${g.from}` : 'mail with no visible From domain';
      const via = g.env ? ` and uses the return path ${g.env}` : ' with no return path';
      const where = `${g.ips.size} address${g.ips.size === 1 ? '' : 'es'}`;
      const fix = g.env && g.env !== g.from && !g.env.endsWith(`.${g.from}`)
        ? 'If you send from this service, sign its mail with DKIM for your domain (SPF alone cannot pass because its return path is another domain).'
        : 'If you send from this service, add it to your SPF record or sign its mail with DKIM; if you do not, it is someone pretending to be you and a reject policy will stop it.';
      return { text: `${g.count.toLocaleString()} messages from ${where}: ${who}${via}. ${g.blocked > 0 ? `${g.blocked.toLocaleString()} were already blocked. ` : ''}${fix}`, messages: g.count, share: total > 0 ? Math.round((g.count / total) * 1000) / 10 : 0 };
    });
}
