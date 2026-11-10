/**
 * What to tell a person about a new password while they type it, before the server is asked. The rules are the server's own (services/api/app/core/password_policy.py: 12 to 128 characters,
 * no space at either end, different from the current one); the server still decides, this only saves a failed attempt.
 */
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;
/** From this length a password made of several words is hard to guess whatever it is made of. */
export const PASSWORD_LONG = 16;

export function passwordHint(next: string, current = ''): { text: string; ok: boolean } | null {
  if (next === '') return null;
  if (next.length < PASSWORD_MIN) {
    const more = PASSWORD_MIN - next.length;
    return { text: `${more} more character${more === 1 ? '' : 's'} needed (at least ${PASSWORD_MIN}).`, ok: false };
  }
  if (next.length > PASSWORD_MAX) return { text: `Too long: at most ${PASSWORD_MAX} characters.`, ok: false };
  if (next.trim() !== next) return { text: 'It cannot start or end with a space.', ok: false };
  if (current !== '' && next === current) return { text: 'It must be different from the current password.', ok: false };
  if (next.length < PASSWORD_LONG) return { text: 'Long enough. Longer is stronger: three or four unrelated words work well.', ok: true };
  return { text: 'Good length.', ok: true };
}
