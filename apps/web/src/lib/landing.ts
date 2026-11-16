/** Where a person goes after signing in: a client dashboard sign-in (role client_viewer) always lands on the client dashboard, whatever page they were headed for; everyone else goes where they were headed. */
export const CLIENT_PORTAL_PATH = '/client-portal';

export function landingFor(role: string | undefined | null, next: string): string {
  return role === 'client_viewer' ? CLIENT_PORTAL_PATH : next;
}
