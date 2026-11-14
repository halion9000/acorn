/**
 * Sign out someone who has not touched the console for four hours.
 *
 * "Active" means a person did something in this browser: moved or clicked the mouse, pressed a key, touched the screen or scrolled, in ANY tab of the console. Pages that refresh
 * themselves in the background do not count, or an unattended screen would stay signed in for the 7 days the refresh token lasts. The time of the last activity is kept in
 * localStorage (written at most every 30 seconds), so every tab agrees and a browser reopened after the limit asks for a login straight away.
 *
 * When the limit passes, the server is told to end the session (the access and refresh tokens stop working, not just this browser's copy), the saved sign-in is cleared and the
 * person goes to the login page with a note saying why.
 */

import { AUTH_ACTIVITY_KEY, AUTH_TOKEN_KEY, clearSession, revokeServerSession, sessionHooks } from './auth-session';

/** Four hours. */
export const IDLE_LIMIT_MS = 4 * 60 * 60 * 1000;
export const ACTIVITY_KEY = AUTH_ACTIVITY_KEY;
/** The login page shows its "signed out for inactivity" note for this value of ``?reason=``. */
export const IDLE_REASON = 'idle';

const WRITE_EVERY_MS = 30_000;
const CHECK_EVERY_MS = 60_000;
const EVENTS = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'wheel'] as const;

function read(): number | null {
  try {
    const raw = window.localStorage.getItem(ACTIVITY_KEY);
    const n = raw === null ? NaN : Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function write(at: number): void {
  try {
    window.localStorage.setItem(ACTIVITY_KEY, String(at));
  } catch {
    /* storage unavailable: the in-memory time below still works for this tab */
  }
}

/** True when the last activity is more than the limit before ``now``. With no time recorded at all, nobody has been seen, so it is not idle (the first activity starts the clock). */
export function isIdle(lastActive: number | null, now: number, limit = IDLE_LIMIT_MS): boolean {
  return lastActive !== null && now - lastActive > limit;
}

/**
 * Start watching. Returns a function that stops it. ``onIdle`` runs once when the limit passes (it defaults to ending the session and going to the login page). ``now`` is replaceable in
 * tests. Nothing happens for a browser holding no saved sign-in.
 */
export function startIdleWatch(opts: { onIdle?: () => void; now?: () => number; limit?: number } = {}): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const now = opts.now ?? Date.now;
  const limit = opts.limit ?? IDLE_LIMIT_MS;
  const onIdle = opts.onIdle ?? signOutIdle;
  let memory = read() ?? now();
  let lastWrite = 0;
  let fired = false;

  // A browser opened again after the limit (or a tab left open over the weekend) is checked before anything else.
  const check = () => {
    if (fired) return;
    const seen = Math.max(memory, read() ?? 0);
    if (isIdle(seen, now(), limit)) {
      fired = true;
      onIdle();
    }
  };
  check();

  const touch = () => {
    const t = now();
    // A person moving the mouse on a tab that was already past the limit is too late: the check decides first.
    if (isIdle(Math.max(memory, read() ?? 0), t, limit)) {
      check();
      return;
    }
    memory = t;
    if (t - lastWrite >= WRITE_EVERY_MS) {
      lastWrite = t;
      write(t);
    }
  };
  if (read() === null) write(memory);
  for (const e of EVENTS) window.addEventListener(e, touch, { passive: true, capture: true });
  const timer = setInterval(check, CHECK_EVERY_MS);
  const onVisible = () => {
    if (document.visibilityState === 'visible') check();
  };
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    for (const e of EVENTS) window.removeEventListener(e, touch, { capture: true });
    clearInterval(timer);
    document.removeEventListener('visibilitychange', onVisible);
  };
}

/** End the session on the server, clear this browser's sign-in and go to the login page, which says why. */
export async function signOutIdle(): Promise<void> {
  let here = '/';
  try {
    here = `${window.location.pathname}${window.location.search}`;
  } catch {
    /* keep "/" */
  }
  await revokeServerSession();
  clearSession();
  try {
    window.localStorage.removeItem(ACTIVITY_KEY);
  } catch {
    /* storage unavailable */
  }
  sessionHooks.redirectToLogin(here, IDLE_REASON);
}

/** Start the clock for a fresh sign-in (the login page calls this once the tokens are saved), so a login after a long absence is not judged by the old time. */
export function markActive(at: number = Date.now()): void {
  write(at);
}

/** Whether this browser holds a saved sign-in (so there is something to time out). */
export function hasSignIn(): boolean {
  try {
    return Boolean(window.localStorage.getItem(AUTH_TOKEN_KEY));
  } catch {
    return false;
  }
}
