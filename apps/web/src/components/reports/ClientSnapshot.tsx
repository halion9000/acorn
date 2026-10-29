'use client';

/**
 * What A.C.O.R.N knows about one client beyond its alerts, for the top of the Executive Digest.
 *
 * The digest counts alerts and cases in a window, so a client with no alerts that week (more than half of them) read as a page of zeros even though A.C.O.R.N holds its devices, people, Multi-Factor
 * and Microsoft Secure Score. This section reads the same numbers the Client Review page does (GET /client-review/{id}) and says them in a few lines, each with a link to the list behind it.
 */
import Link from 'next/link';
import useSWR from 'swr';

import { TOOL_NAMES, type Review } from '@/app/(app)/reports/client-review/ClientReview';
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
    </section>
  );
}
