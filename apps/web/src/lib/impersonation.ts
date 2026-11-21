/**
 * Impersonation (Settings > Members > Impersonate): an administrator signs in as another person and sees the console exactly as they do, with their permissions, until they end it.
 *
 * The server mints a one-hour token that names the real administrator. It is kept for this browser tab only (see auth-session.ts), every request carries it instead of the administrator's own sign-in,
 * and the saved user is swapped for the person's so menus and pages follow their permissions. Ending puts the administrator's own user back and tells the server, which writes it to the audit log.
 */
import { authFetch, AUTH_USER_BEFORE_IMPERSONATION_KEY, clearImpersonation, getImpersonation, setImpersonation } from './auth-session';
import { AUTH_USER_KEY } from './auth-session';

interface Started {
  access_token: string;
  label: string;
}

/** Start impersonating `userId`. Returns an error message when the server refuses (its own words), or null when it started. The caller reloads the console afterwards. */
export async function startImpersonation(userId: string, adminLabel: string): Promise<string | null> {
  if (getImpersonation() !== null) return 'End the current impersonation first.';
  const res = await authFetch(`/api/v1/auth/impersonate/${encodeURIComponent(userId)}`, { method: 'POST' });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    return typeof body.detail === 'string' ? body.detail : `The API answered ${res.status}`;
  }
  const started = (await res.json()) as Started;
  try {
    const mine = window.localStorage.getItem(AUTH_USER_KEY);
    if (mine) window.localStorage.setItem(AUTH_USER_BEFORE_IMPERSONATION_KEY, mine);
  } catch {
    /* storage unavailable */
  }
  setImpersonation({ token: started.access_token, label: started.label, by: adminLabel });
  // From here every request is the person's. Save who they are so menus follow their permissions.
  try {
    const me = await authFetch('/api/v1/auth/me');
    if (me.ok) window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(await me.json()));
  } catch {
    /* the console reads it again on load */
  }
  return null;
}

/** End the impersonation: tell the server (best effort; the token also expires within the hour), then put the administrator's own user back. */
export async function endImpersonation(): Promise<void> {
  if (getImpersonation() === null) return;
  try {
    await authFetch('/api/v1/auth/impersonate/end/now', { method: 'POST' });
  } catch {
    /* the token expires by itself */
  }
  clearImpersonation();
}
