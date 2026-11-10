/** What a member list row says about a person's second factor: the text, and whether it is a warning (they have none, so a stolen password is enough). */
export function secondFactorBadge(m: { passkeys?: number; authenticator?: boolean }): { text: string; warn: boolean } | null {
  // A server that does not send the fields (an older one) says nothing, rather than claiming nobody is protected.
  if (m.passkeys === undefined && m.authenticator === undefined) return null;
  const passkeys = m.passkeys ?? 0;
  const parts: string[] = [];
  if (passkeys > 0) parts.push(passkeys === 1 ? '1 passkey' : `${passkeys} passkeys`);
  if (m.authenticator) parts.push('authenticator app');
  if (parts.length === 0) return { text: 'No second factor', warn: true };
  return { text: parts.join(' + '), warn: false };
}
