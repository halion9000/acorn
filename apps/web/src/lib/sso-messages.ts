/** What the sign-in page says when Sign in with Microsoft sends the person back with `?sso_error=<code>`. The codes are the server's (sso_microsoft.py); an unknown one gets the general sentence. */
const MESSAGES: Record<string, string> = {
  state: 'That sign-in took too long or was opened twice. Start again.',
  denied: 'Microsoft did not complete the sign-in. Start again, or ask an administrator if it keeps happening.',
  token: 'Microsoft would not confirm the sign-in. Try again in a moment.',
  tenant: 'That Microsoft account belongs to a different organization than this workspace allows.',
  group: 'Your Microsoft account is not in the group allowed to use A.C.O.R.N. Ask an administrator to add you.',
  disabled: 'Your account here is turned off. Ask an administrator.',
  linked: 'That account here is already linked to a different Microsoft account. Ask an administrator.',
  no_account: 'There is no account here for that Microsoft sign-in. Ask an administrator.',
  identity: 'Microsoft did not say who you are. Try again, or ask an administrator.',
  unavailable: 'Sign-in is temporarily unavailable. Try again in a moment.',
};

export function ssoErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null;
  return MESSAGES[code] ?? 'Sign in with Microsoft did not work. Try again, or ask an administrator.';
}
