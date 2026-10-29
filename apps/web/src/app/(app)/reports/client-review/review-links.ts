/**
 * Where to look at what is behind a readiness answer: the people with no Multi-Factor, the computers missing a tool, the agents that stopped checking in.
 * Only a question with a page that shows exactly that gets a link; the rest have none (a link that lands on something else is worse than no link).
 */

export interface ReviewLink {
  label: string;
  href: string;
}

interface Counts {
  mfa?: { without_mfa?: number; admins_without_mfa?: number } | null;
}

const q = (clientId: string, extra: string): string => `client=${encodeURIComponent(clientId)}${extra ? `&${extra}` : ''}`;

/** The link for one readiness question of one client, or null when no page shows what it is about. ``met`` answers get none: there is nothing to chase. */
export function reviewLink(key: string, status: string, clientId: string, counts: Counts = {}): ReviewLink | null {
  if (status === 'met' || status === 'unknown') return null;
  const people = (n: number | undefined, what: string): string => (n && n > 0 ? `See the ${n} ${what}` : `See the ${what}`);
  switch (key) {
    case 'mfa_everyone':
      return { label: people(counts.mfa?.without_mfa, 'people without Multi-Factor'), href: `/settings/mfa?${q(clientId, 'which=without')}` };
    case 'mfa_admins':
      return { label: people(counts.mfa?.admins_without_mfa, 'administrators without Multi-Factor'), href: `/settings/mfa?${q(clientId, 'which=admins')}` };
    case 'edr':
      return { label: 'See the computers missing Huntress', href: `/devices?${q(clientId, 'missing=huntress')}` };
    case 'management':
      return { label: 'See the computers missing NinjaOne', href: `/devices?${q(clientId, 'missing=ninjaone')}` };
    case 'dns':
      return { label: 'See the computers missing DNSFilter', href: `/devices?${q(clientId, 'missing=dnsfilter')}` };
    case 'privilege':
      return { label: 'See the computers missing AutoElevate', href: `/devices?${q(clientId, 'missing=autoelevate&os=windows')}` };
    case 'agents_reporting':
      return { label: 'See the agents not checking in', href: `/devices?${q(clientId, 'stale=1')}` };
    case 'disk_encryption':
      return { label: 'See the computers that are not encrypted', href: `/devices?${q(clientId, 'encryption=not_encrypted')}` };
    case 'secure_score':
      return { label: 'See the Secure Score', href: `/settings/secure-score?${q(clientId, '')}` };
    default:
      return null;
  }
}
