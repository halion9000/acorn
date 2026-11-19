/** Other words people use for a sidebar page, by its address, so typing "billing" or "2fa" in the palette finds the page that is called something else. */
export const PAGE_WORDS: Record<string, string[]> = {
  '/settings/finance': ['finance settings', 'burdened rate', 'labor rate', 'hourly rate', 'hourly cost', 'wages', 'payroll cost'],
  '/settings/billing': ['billing', 'invoice', 'invoices', 'licenses', 'licenses', 'seats', 'counts', 'charges', 'margin'],
  '/settings/mfa': ['mfa', '2fa', 'two-factor', 'second factor', 'authenticator', 'multi factor'],
  '/settings/secure-score': ['secure score', 'microsoft score', 'posture score'],
  '/settings/signin-scores': ['sign-in', 'signin', 'login', 'risky sign-ins'],
  '/settings/dmarc': ['dmarc', 'spf', 'dkim', 'email authentication', 'spoofing'],
  '/settings/client-posture': ['posture', 'checks', 'nist', 'compliance checks'],
  '/settings/fleet-posture': ['fleet', 'devices posture', 'patching'],
  '/settings/client-docs': ['documentation', 'it glue', 'runbooks'],
  '/vulnerabilities': ['cve', 'patching', 'unpatched', 'end of support'],
  '/inventory': ['stock', 'checkout', 'spares', 'hardware'],
  '/reports/digest': ['executive digest', 'weekly', 'summary', 'report'],
  '/reports/client-review': ['qbr', 'client review', 'quarterly'],
  '/reports/device-versions': ['firmware', 'agent version', 'huntress version', 'outdated'],
  '/vcio-risk-scoring': ['client risk score', 'vcio', 'risk scoring', 'risk score', 'trend', 'business review', 'scorecard', 'nist csf', 'tech stack'],
  '/honeytokens': ['canary', 'decoy', 'tripwire'],
  '/fim': ['file integrity', 'file changes'],
  '/devices/environment': ['network map', 'drawing', 'diagram', 'topology'],
  '/remote-tools': ['remote access', 'screen share', 'rmm'],
  '/devices': ['machines', 'computers', 'endpoints', 'laptops', 'servers', 'assets'],
  '/identities': ['users', 'people', 'accounts', 'mailboxes'],
  '/shifts': ['handover', 'on call', 'rota', 'schedule'],
  '/easm': ['attack surface', 'external', 'exposed', 'internet facing'],
  '/playbooks': ['response', 'runbooks', 'workflows', 'response and defense'],
  '/automation/tickets': ['automation', 'auto ticket', 'automatic tickets', 'halo tickets', 'ticket rules'],
  '/automation/scripts': ['automation', 'auto script', 'automatic scripts', 'script rules', 'script log', 'ninja scripts'],
  '/automation/hubspot': ['automation', 'hubspot', 'crm', 'halo to hubspot', 'ticket sync', 'onboarding'],
  '/compliance': ['frameworks', 'controls', 'audit', 'cis', 'nist', 'secureframe', 'control health'],
  '/compliance/frameworks': ['soc 2', 'iso 27001', 'hipaa', 'pci', 'nist', 'cis', 'controls', 'evidence'],
  '/compliance/controls': ['controls', 'control health', 'evidence', 'healthy', 'unhealthy'],
  '/compliance/access-reviews': ['access review', 'who has access', 'user access', 'least privilege', 'recertification'],
  '/compliance/people': ['people', 'onboarding', 'offboarding', 'new hire', 'leaver', 'joiner', 'checklist'],
  '/compliance/calendar': ['calendar', 'due', 'due dates', 'deadlines', 'overdue', 'schedule', 'renewal'],
  '/compliance/questionnaires': ['questionnaire', 'security questionnaire', 'vendor assessment', 'answer library', 'caiq', 'sig'],
  '/metrics/tickets': ['tickets', 'metrics', 'csat', 'satisfaction', 'survey', 'response time', 'created', 'resolved'],
  '/metrics/labor-hours': ['labor hours', 'hours', 'time entries', 'engineer', 'utilization', 'metrics'],
  '/metrics/staff-metrics': ['staff metrics', 'utilization', 'weekly', 'team', 'tickets closed'],
  '/metrics/pods': ['pods', 'teams', 'resolved', 'days off', 'holidays'],
  '/metrics/ticket-updates': ['ticket updates', 'team member', 'weekly', 'activity'],
  '/metrics/dialpad': ['dialpad', 'calls', 'phone', 'triage', 'hours on call'],
  '/metrics/staff-hours': ['staff hours', 'distribution', 'hours by type', 'time'],
  '/metrics/scorecard': ['scorecard', 'score', 'grade', 'service desk', 'performance'],
  '/metrics/ticket-resolution': ['resolution', 'resolved', 'resolution time', 'hours to resolve'],
  '/metrics/ticket-volume': ['volume', 'ticket volume', 'categories', 'stale tickets', 'priority'],
  '/metrics/monthly-invoicing': ['invoicing', 'revenue', 'billed', 'billing category', 'invoice lines'],
  '/metrics/customer-experience': ['customer experience', 'csat', 'satisfaction', 'surveys', 'simplesat'],
  '/metrics/monthly-licensing': ['licensing', 'licenses', 'monthly licensing', 'seats', 'counts'],
  '/metrics/user-roles': ['user roles', 'admin roles', 'global administrator', 'microsoft 365 roles'],
  '/metrics/client-summary': ['client summary', 'review', 'qbr', 'print', 'pdf', 'customer dashboard', 'metrics'],
  '/finance/profitability': ['profit', 'margin', 'revenue', 'labor cost', 'money', 'finance'],
  '/finance/net-income': ['net income', 'profit', 'overhead', 'industry', 'utilization', 'hours', 'ranking', 'cost', 'finance'],
  '/finance/billing-sync': ['billing sync', 'license', 'approve', 'push', 'halo', 'saas billing', 'difference', 'quantity'],
  '/compliance/audits': ['audit', 'auditor', 'evidence request', 'pbc', 'soc 2 audit'],
  '/compliance/trust-center': ['trust center', 'trust page', 'security page', 'customers', 'share compliance'],
  '/compliance/tests': ['tests', 'automated tests', 'control tests', 'continuous monitoring', 'passing', 'failing'],
  '/compliance/policies': ['policy', 'policies', 'review calendar', 'procedures'],
  '/compliance/vendors': ['vendors', 'third party', 'suppliers', 'vendor risk', 'vendor review'],
  '/compliance/risk-register': ['risks', 'risk register', 'treatment', 'residual', 'likelihood'],
};

export interface PaletteNavItem {
  label: string;
  href: string;
  keywords: string[];
}

/**
 * The palette's page list: the curated entries as they are, then every other sidebar page (in sidebar order, once each) with its label and the extra words above. A page the person's role
 * hides is not in `sections` and so is not offered. Settings pages given in `settingsPages` follow, each once, unless already listed.
 */
export function paletteNavItems(
  curated: PaletteNavItem[],
  sections: { items: { label: string; href: string }[] }[],
  settingsPages: { label: string; href: string; description?: string }[] = [],
): PaletteNavItem[] {
  const seen = new Set(curated.map((c) => c.href));
  const extra: PaletteNavItem[] = [];
  for (const section of sections) {
    for (const item of section.items) {
      if (seen.has(item.href)) continue;
      seen.add(item.href);
      extra.push({ label: item.label, href: item.href, keywords: PAGE_WORDS[item.href] ?? [] });
    }
  }
  // Settings pages that are their own screens (audit log, platform health, retention...): found by their name or by a word from their description.
  for (const page of settingsPages) {
    if (seen.has(page.href)) continue;
    seen.add(page.href);
    extra.push({ label: page.label, href: page.href, keywords: [...(PAGE_WORDS[page.href] ?? []), ...(page.description ? [page.description.toLowerCase()] : [])] });
  }
  const words = (c: PaletteNavItem): PaletteNavItem => ({ ...c, keywords: [...c.keywords, ...(PAGE_WORDS[c.href] ?? []).filter((w) => !c.keywords.includes(w))] });
  return [...curated.map(words), ...extra];
}

/** How many past searches the palette remembers. */
export const SEARCHES_KEPT = 5;

/**
 * The remembered searches after one more is used: the new one first, an earlier copy of it (whatever its letter case) dropped, at most SEARCHES_KEPT kept. Text under two characters, or blank, is
 * not remembered. The input list is not changed. Pure.
 */
export function rememberSearch(list: readonly string[], text: string): string[] {
  const t = text.trim();
  if (t.length < 2) return [...list];
  return [t, ...list.filter((s) => s.toLowerCase() !== t.toLowerCase())].slice(0, SEARCHES_KEPT);
}

/** The pages the palette has always listed, each with the other words people type for it. */
export const CURATED_PAGES: PaletteNavItem[] = [
  { label: 'SOC Dashboard',   href: '/dashboard',    keywords: ['home', 'overview', 'metrics', 'dashboard'] },
  { label: 'Alerts',          href: '/alerts',       keywords: ['notifications', 'incidents'] },
  { label: 'Cases',           href: '/cases',        keywords: ['investigations', 'tickets'] },
  { label: 'Hunt',            href: '/hunt',         keywords: ['threat hunting', 'search', 'kql', 'esql'] },
  { label: 'Explore',         href: '/explore',      keywords: ['data explorer', 'lake', 'sql', 'bi', 'query', 'identity', 'intel'] },
  { label: 'Detection Rules', href: '/detection',    keywords: ['rules', 'detections', 'sigma'] },
  { label: 'Threat Intel',    href: '/threat-intel', keywords: ['ioc', 'feeds', 'cti'] },
  { label: 'Attack Graph',    href: '/graph',        keywords: ['graph', 'paths', 'cytoscape'] },
  { label: 'Leafy',           href: '/copilot',      keywords: ['copilot', 'assistant', 'chat', 'ai'] },
  { label: 'Connectors',      href: '/settings/connectors', keywords: ['integrations', 'sources'] },
  { label: 'Client mapping',  href: '/settings/client-mapping', keywords: ['map', 'unmapped', 'clients', 'tools'] },
  { label: 'Toolbox',         href: '/toolbox', keywords: ['offboard', 'onboard', 'mfa', 'password', 'm365', 'mailbox', 'user'] },
  { label: 'Client families', href: '/settings/families', keywords: ['parent', 'child', 'group', 'siblings', 'linked'] },
  { label: 'Audit Log',       href: '/settings/audit', keywords: ['activity', 'events'] },
  { label: 'Settings',        href: '/settings',     keywords: ['preferences', 'profile', 'tenant'] },
  { label: 'Upcoming improvements', href: '/settings/roadmap', keywords: ['roadmap', 'features', 'backlog', 'priorities', 'pending', 'todo'] },
  { label: 'ACORN Setup Guide', href: '/settings/guide', keywords: ['help', 'how to', 'docs', 'documentation', 'manual', 'user guide', 'setup'] },
  { label: "What's new", href: '/settings/whats-new', keywords: ['new', 'changes', 'release', 'latest', 'added', 'features', 'changelog'] },
];

/** Every distinct word that finds a page in the palette: the words of its name and of its other words, in lower case. */
export function searchWords(item: PaletteNavItem): string[] {
  const words = [item.label, ...item.keywords].flatMap((s) => s.toLowerCase().split(/[^a-z0-9]+/)).filter((w) => w.length > 1);
  return [...new Set(words)];
}
