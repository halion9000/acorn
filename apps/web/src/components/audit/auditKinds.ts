/** The kinds of event the filter offers when the server cannot say which exist: the ones people ask for most. */
export const FALLBACK_KINDS: { value: string; label: string }[] = [
  { value: 'cases:', label: 'Cases' },
  { value: 'alerts:', label: 'Alerts' },
  { value: 'playbooks:', label: 'Playbooks' },
  { value: 'detections:', label: 'Detections' },
  { value: 'connectors:', label: 'Connectors' },
  { value: 'role:', label: 'Roles' },
  { value: 'tenant:', label: 'Members and access' },
  { value: 'auth:', label: 'Auth' },
];

const WORDS: Record<string, string> = {
  cases: 'Cases',
  alerts: 'Alerts',
  playbooks: 'Playbooks',
  detections: 'Detections',
  connectors: 'Connectors',
  role: 'Roles',
  tenant: 'Members and access',
  auth: 'Sign-in and account',
  sso: 'Single sign-on',
};

/** "api_keys:" with no friendly name becomes "Api keys". */
function plain(prefix: string): string {
  const base = prefix.replace(/:$/, '').replace(/[_-]+/g, ' ').trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : prefix;
}

/**
 * The options of the action filter: exactly the kinds of event this trail holds (so the filter cannot ask for a prefix nothing is logged under), each with how many there are, most frequent first.
 * With no answer from the server, or an empty one, the usual kinds are offered instead.
 */
export function auditKindOptions(kinds: { prefix: string; count: number }[] | undefined | null): { value: string; label: string }[] {
  if (!Array.isArray(kinds) || kinds.length === 0) return FALLBACK_KINDS;
  return kinds
    .filter((k) => typeof k.prefix === 'string' && k.prefix.endsWith(':'))
    .map((k) => ({ value: k.prefix, label: `${WORDS[k.prefix.slice(0, -1)] ?? plain(k.prefix)} (${k.count})` }));
}
