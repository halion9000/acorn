/**
 * "My vendors": a vendor's owner is typed text (a name or an e-mail address), so it is matched to the signed-in person by what they sign in with and what they are called: their e-mail address,
 * the part of it before the @, their account name or their username, compared in lower case. An owner field that says nothing matches nobody. Pure.
 */

export interface WhoAmI {
  email?: string | null;
  account_name?: string | null;
  username?: string | null;
}

const norm = (s: string | null | undefined): string => (s ?? '').trim().toLowerCase();

/** The ways this person might be written as an owner. */
export function aliasesOf(who: WhoAmI): string[] {
  const email = norm(who.email);
  const out = [email, email.split('@')[0] ?? '', norm(who.account_name), norm(who.username)].filter((a) => a.length >= 2);
  return [...new Set(out)];
}

/** True when the owner text is this person: it equals one of their names, or it holds their full e-mail address (as "Hal <hal@example.com>"). */
export function ownedBy(owner: string | null | undefined, who: WhoAmI): boolean {
  const o = norm(owner);
  if (!o) return false;
  const email = norm(who.email);
  return aliasesOf(who).some((a) => o === a) || (email.includes('@') && o.includes(email));
}

/** The vendors this person owns (pure). */
export function myVendors<T extends { owner: string | null }>(vendors: T[], who: WhoAmI | null): T[] {
  return who ? vendors.filter((v) => ownedBy(v.owner, who)) : [];
}
