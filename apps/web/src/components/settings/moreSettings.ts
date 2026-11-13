/** Settings pages that are their own screens. They were reachable only by typing their address; this lists them. */
/** `requires`: the capability (a View permission of its Settings area) a person needs to be shown the page; the server checks every action itself. A page with none is shown to everyone who reaches Settings. */
export const MORE_SETTINGS: { href: string; label: string; description: string; requires?: string }[] = [
  { href: '/settings/rbac', label: 'Roles & permissions', description: 'Who can do what, and which sidebar pages each role sees' },
  { href: '/settings/connectors', label: 'Connectors', description: 'The tools connected to A.C.O.R.N, and the ones CORE manages' },
  { href: '/settings/client-mapping', label: 'Client mapping', description: 'Link the clients of each tool to your client tenants' },
  { href: '/settings/audit', label: 'Audit log', description: 'Every administrative and security event, searchable' },
  { href: '/settings/client-cleanup', label: 'Client cleanup', description: 'Clients with nothing in them, and tool clients mapped to the wrong one' },
  { href: '/settings/platform-health', label: 'Platform health', description: 'Whether every service is answering' },
  { href: '/settings/onboarding', label: 'Client onboarding', description: 'How far each client has got: tools linked, devices, people, checks and alerts' },
  { href: '/settings/retention', label: 'Data retention', description: 'What is kept, for how long, and what ends it', requires: 'settings_data' },
  { href: '/settings/costs', label: 'Cost dashboard', description: 'AI spend, automation activity and savings from bringing your own key' },
  { href: '/settings/triage', label: 'Auto-close', description: 'How sure AI triage must be to close an alert itself', requires: 'settings_automation' },
  { href: '/settings/cipp-actions', label: 'CIPP actions', description: 'What CORE can do to client Microsoft 365 tenants through CIPP, whether it is switched on, and what it has been asked to do' },
  { href: '/settings/revisions', label: 'Revisions', description: 'Every revision of A.C.O.R.N so far, newest first, and the current version number' },
  { href: '/settings/guide', label: 'ACORN Setup Guide', description: 'How to set up and use A.C.O.R.N, page by page (the former User guide)' },
  { href: '/settings/business-context', label: 'Business context rules', description: "Rules that adjust an alert's importance for a client before it is triaged" },
  { href: '/settings/tickets', label: 'Tickets', description: 'The HaloPSA status a resolved incident moves its ticket to', requires: 'settings_tickets' },
  { href: '/settings/vcio-risk-scoring', label: 'Client Risk Score', description: 'How every client is scored: severity points, answer credits, the critical-gap cap, rating bands and category weights', requires: 'settings_clients' },
];
