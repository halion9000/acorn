import { csvText } from '@/lib/csv';

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

/** The members whose second-factor fields were sent and who have no passkey and no authenticator app (an older server that sends neither field is not counted as "none"). */
export function withoutSecondFactor<T extends { passkeys?: number; authenticator?: boolean; is_active?: boolean }>(members: T[]): T[] {
  return members.filter((m) => m.is_active !== false && secondFactorBadge(m)?.warn === true);
}

/** The members list as spreadsheet text (what Export CSV saves): who they are, their role and whether they can sign in, and the second factor each has. */
export function membersCsvText(
  members: {
    account_name: string;
    username?: string | null;
    email?: string | null;
    role: string;
    is_active?: boolean;
    last_login?: string | null;
    passkeys?: number;
    authenticator?: boolean;
    custom_roles?: { name: string }[];
  }[],
): string {
  return csvText(
    ['Account', 'Name', 'Email', 'Role', 'Custom roles', 'Active', 'Last sign-in', 'Passkeys', 'Authenticator app', 'Second factor'],
    members.map((m) => {
      const known = m.passkeys !== undefined || m.authenticator !== undefined;
      return [
        m.account_name,
        m.username,
        m.email,
        m.role,
        (m.custom_roles ?? []).map((r) => r.name).join('; '),
        m.is_active === false ? 'no' : 'yes',
        m.last_login,
        known ? (m.passkeys ?? 0) : '',
        known ? (m.authenticator ? 'yes' : 'no') : '',
        secondFactorBadge(m)?.text ?? 'not reported',
      ];
    }),
  );
}

/** How many recovery codes left is few enough to say so. */
export const FEW_RECOVERY_CODES = 2;

/** A sentence for when the recovery codes are nearly used up, or null while there are enough. */
export function recoveryCodesWarning(left: number): string | null {
  if (left > FEW_RECOVERY_CODES) return null;
  if (left <= 0) return 'No recovery codes left. If you lose your phone you cannot sign in: make new ones now.';
  return `Only ${left} recovery code${left === 1 ? '' : 's'} left. Make new ones before you run out.`;
}
