'use client';

/**
 * What A.C.O.R.N knows about one client beyond its alerts, for the top of the Executive Digest.
 *
 * The digest counts alerts and cases in a window, so a client with no alerts that week (more than half of them) read as a page of zeros even though A.C.O.R.N holds its devices, people, Multi-Factor
 * and Microsoft Secure Score. This section reads the same numbers the Client Review page does (GET /client-review/{id}) and says them in a few lines, each with a link to the list behind it.
 */
import Link from 'next/link';
import useSWR from 'swr';

import { TOOL_NAMES, type ReadinessItem, type Review } from '@/app/(app)/reports/client-review/ClientReview';
import { reviewLink } from '@/app/(app)/reports/client-review/review-links';
import { authFetch } from '@/lib/auth-session';

async function readReview(id: string): Promise<Review> {
  const res = await authFetch(`/api/v1/client-review/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as Review;
}

const q = (id: string, extra: string): string => `client=${encodeURIComponent(id)}${extra ? `&${extra}` : ''}`;

export interface SnapshotLine {
  label: string;
  text: string;
  href?: string;
  linkText?: string;
}

/** The lines of a snapshot, from a review. Pure so every wording is tested with plain numbers. */
export function snapshotLines(r: Review): SnapshotLine[] {
  const lines: SnapshotLine[] = [];
  const d = r.devices;
  if (d.endpoints === 0) {
    lines.push({ label: 'Devices', text: 'No computers are listed for this client.' });
  } else {
    const gaps = d.coverage.filter((c) => c.of > 0 && c.enrolled !== false && c.have < c.of);
    lines.push({
      label: 'Devices',
      text: `${d.endpoints} computers${d.stale_agents ? `, ${d.stale_agents} with an agent not checking in` : ''}${d.offline ? `, ${d.offline} offline` : ''}.`,
      href: `/devices?${q(r.client_id, '')}`,
      linkText: 'See the devices',
    });
    for (const c of gaps) {
      lines.push({
        label: TOOL_NAMES[c.tool] ?? c.tool,
        text: `${c.have} of ${c.of} computers (${c.percent ?? Math.round((100 * c.have) / c.of)}%); ${c.of - c.have} missing.`,
        href: `/devices?${q(r.client_id, `missing=${c.tool}`)}`,
        linkText: `See the ${c.of - c.have} missing`,
      });
    }
    for (const c of d.coverage.filter((x) => x.enrolled === false)) {
      lines.push({ label: TOOL_NAMES[c.tool] ?? c.tool, text: 'Not currently enrolled for this client.' });
    }
  }
  if (r.mfa) {
    lines.push({
      label: 'Multi-Factor',
      text: `${r.mfa.with_mfa} of ${r.mfa.people} people have a required second factor; ${r.mfa.without_mfa} have none${r.mfa.admins_without_mfa ? `, ${r.mfa.admins_without_mfa} of them administrators` : ''}.`,
      href: r.mfa.without_mfa > 0 ? `/settings/mfa?${q(r.client_id, 'which=without')}` : undefined,
      linkText: `See the ${r.mfa.without_mfa} people`,
    });
  } else {
    lines.push({ label: 'Multi-Factor', text: 'No Multi-Factor data has arrived for this client.' });
  }
  lines.push({
    label: 'Microsoft Secure Score',
    text: r.secure_score ? `${r.secure_score.percent}% (${r.secure_score.current} of ${r.secure_score.max})${r.secure_score.average != null ? `, Microsoft's average is ${r.secure_score.average}` : ''}.` : 'Not read for this client.',
  });
  lines.push({
    label: `Alerts and cases, last ${r.window_days} days`,
    text: `${r.alerts.open} alerts open (${r.alerts.critical_open} critical, ${r.alerts.high_open} high); ${r.alerts.opened_30d} raised and ${r.alerts.closed_30d} closed. ${r.cases.open} cases open.`,
    href: `/alerts?${q(r.client_id, '')}&status=open`,
    linkText: 'See the open alerts',
  });
  lines.push({
    label: 'Cyber-insurance readiness',
    text: `${r.readiness.met} met, ${r.readiness.partly} partly, ${r.readiness.not_met} not met, ${r.readiness.unknown} not known.`,
    href: `/reports/client-review?${q(r.client_id, '')}`,
    linkText: 'Open the Client Review',
  });
  return lines;
}

/** The readiness answers an executive reads together, by theme. An answer in no theme is not shown here (the Client Review has them all). */
export const THEMES: { title: string; keys: string[] }[] = [
  { title: 'Backups and recovery', keys: ['backups', 'mailbox_backup_coverage', 'backup_appliance_current', 'backups_verified'] },
  { title: 'Computers: patching and protection', keys: ['critical_updates', 'supported_os', 'antivirus_current', 'protection_healthy', 'edr', 'management', 'agents_reporting', 'hardening', 'admin_rights_control', 'privilege', 'disk_encryption', 'dns', 'dns_threat_blocking'] },
  { title: 'Identity and sign-in', keys: ['mfa_everyone', 'mfa_admins', 'network_admin_mfa', 'account_risk', 'secure_score'] },
  { title: 'Email and domains', keys: ['email_domain_records', 'domain_expiry', 'certificate_expiry'] },
  { title: 'Exposure and insurance', keys: ['external_exposure', 'cyber_insurance_baseline', 'ai_tool_governance', 'patching'] },
];

export interface Theme {
  title: string;
  met: number;
  known: number;
  problems: ReadinessItem[];
}

/** Each theme with how many of its answers are met out of those A.C.O.R.N could answer, and the ones that are not met or only partly (not met first). Themes with no answer at all are left out. */
export function readinessThemes(items: ReadinessItem[]): Theme[] {
  const out: Theme[] = [];
  for (const t of THEMES) {
    const mine = items.filter((i) => t.keys.includes(i.key) && i.status !== 'unknown');
    if (mine.length === 0) continue;
    const problems = mine.filter((i) => i.status !== 'met').sort((a, b) => (a.status === b.status ? 0 : a.status === 'not_met' ? -1 : 1));
    out.push({ title: t.title, met: mine.length - problems.length, known: mine.length, problems });
  }
  return out;
}

function Themes({ review }: { review: Review }) {
  const themes = readinessThemes(review.readiness.items);
  if (themes.length === 0) return null;
  return (
    <div className="mt-4 border-t border-gray-800 pt-3" data-testid="snapshot-themes">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">Where it stands, by area</h3>
      <ul className="space-y-2.5 text-sm">
        {themes.map((t) => (
          <li key={t.title}>
            <p className="text-gray-200">
              {t.title}: <span className={t.problems.length === 0 ? 'text-emerald-300' : 'text-amber-300'}>{t.met} of {t.known} met</span>
            </p>
            {t.problems.slice(0, 4).map((p) => {
              const link = reviewLink(p.key, p.status, review.client_id, { mfa: review.mfa });
              return (
                <p key={p.key} className="ml-3 text-xs text-gray-400">
                  <span className={p.status === 'not_met' ? 'text-red-300' : 'text-amber-300'}>{p.status === 'not_met' ? 'Not met' : 'Partly'}</span> · {p.question} {p.evidence}
                  {link ? (
                    <>
                      {' '}
                      <Link href={link.href} className="text-sky-300 underline hover:text-sky-200">
                        {link.label} →
                      </Link>
                    </>
                  ) : null}
                </p>
              );
            })}
            {t.problems.length > 4 ? <p className="ml-3 text-xs text-gray-500">{t.problems.length - 4} more in the Client Review.</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ClientSnapshot({ clientId }: { clientId: string }) {
  const { data, error, isLoading } = useSWR(clientId ? ['client-snapshot', clientId] : null, () => readReview(clientId), { revalidateOnFocus: false });
  if (!clientId) return null;
  return (
    <section className="rounded-xl border border-gray-700 bg-gray-900 p-5" aria-label="Client snapshot" data-testid="client-snapshot">
      <h2 className="text-base font-semibold text-white">Client snapshot{data?.client_name ? `: ${data.client_name}` : ''}</h2>
      <p className="mb-3 mt-0.5 text-xs text-gray-500">Devices, people and Microsoft 365 as A.C.O.R.N holds them now. The numbers below this section count alerts and cases in the period.</p>
      {isLoading && !data ? <p className="text-sm text-gray-500">Reading the client…</p> : null}
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          Could not read this client: {error instanceof Error ? error.message : String(error)}
        </p>
      ) : null}
      {data ? (
        <dl className="space-y-1.5 text-sm">
          {snapshotLines(data).map((l) => (
            <div key={l.label} className="flex flex-wrap gap-x-3">
              <dt className="w-56 shrink-0 text-gray-400">{l.label}</dt>
              <dd className="flex-1 text-gray-200">
                {l.text}{' '}
                {l.href ? (
                  <Link href={l.href} className="text-sky-300 underline hover:text-sky-200">
                    {l.linkText} →
                  </Link>
                ) : null}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {data ? <Themes review={data} /> : null}
    </section>
  );
}
