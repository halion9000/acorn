/** Where a person goes after signing in: a client dashboard sign-in (role client_viewer) always lands on the client dashboard and an auditor sign-in on the audit portal, whatever page they were headed for; everyone else goes where they were headed. */
export const CLIENT_PORTAL_PATH = '/client-portal';
export const AUDIT_PORTAL_PATH = '/audit-portal';

export function landingFor(role: string | undefined | null, next: string): string {
  if (role === 'auditor') return AUDIT_PORTAL_PATH;
  return role === 'client_viewer' ? CLIENT_PORTAL_PATH : next;
}
