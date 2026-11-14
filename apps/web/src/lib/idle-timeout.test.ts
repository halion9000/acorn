import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_ACTIVITY_KEY, AUTH_REFRESH_KEY, AUTH_TOKEN_KEY, AUTH_USER_KEY, clearSession, sessionHooks } from './auth-session';
import { ACTIVITY_KEY, IDLE_LIMIT_MS, IDLE_REASON, isIdle, markActive, signOutIdle, startIdleWatch } from './idle-timeout';

const HOUR = 60 * 60 * 1000;

describe('the limit', () => {
  it('is four hours, and only MORE than four hours of silence is idle', () => {
    expect(IDLE_LIMIT_MS).toBe(4 * HOUR);
    expect(isIdle(0, 4 * HOUR)).toBe(false);
    expect(isIdle(0, 4 * HOUR + 1)).toBe(true);
    expect(isIdle(null, 99 * HOUR)).toBe(false); // nothing recorded: the first activity starts the clock
  });
});

describe('watching a browser', () => {
  let stop: () => void = () => undefined;
  let clock = 1_000_000_000_000;
  const now = () => clock;
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
    clock = 1_000_000_000_000;
  });
  afterEach(() => {
    stop();
    vi.useRealTimers();
  });

  it('signs out when four hours pass with no activity, and only once', () => {
    const onIdle = vi.fn();
    stop = startIdleWatch({ onIdle, now });
    clock += 4 * HOUR - 1000;
    vi.advanceTimersByTime(60_000);
    expect(onIdle).not.toHaveBeenCalled();
    clock += 5 * HOUR;
    vi.advanceTimersByTime(60_000);
    vi.advanceTimersByTime(60_000);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('a key press, a click or a scroll starts the four hours again', () => {
    const onIdle = vi.fn();
    stop = startIdleWatch({ onIdle, now });
    for (const type of ['keydown', 'mousedown', 'scroll']) {
      clock += 3 * HOUR;
      window.dispatchEvent(new Event(type));
      vi.advanceTimersByTime(60_000);
    }
    expect(onIdle).not.toHaveBeenCalled();
    clock += 4 * HOUR + 1000;
    vi.advanceTimersByTime(60_000);
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('activity in another tab counts: the time is shared through storage', () => {
    const onIdle = vi.fn();
    stop = startIdleWatch({ onIdle, now });
    clock += 3 * HOUR + 59 * 60_000;
    window.localStorage.setItem(ACTIVITY_KEY, String(clock)); // what the other tab wrote
    clock += 3 * HOUR;
    vi.advanceTimersByTime(60_000);
    expect(onIdle).not.toHaveBeenCalled();
  });

  it('a browser opened again after the limit signs out straight away, before any click can save it', () => {
    window.localStorage.setItem(ACTIVITY_KEY, String(clock - 5 * HOUR));
    const onIdle = vi.fn();
    stop = startIdleWatch({ onIdle, now });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('a click on a tab already past the limit is too late: it signs out rather than reviving the session', () => {
    const onIdle = vi.fn();
    stop = startIdleWatch({ onIdle, now });
    clock += 6 * HOUR; // timers did not run (a sleeping laptop)
    window.dispatchEvent(new Event('mousedown'));
    expect(onIdle).toHaveBeenCalledTimes(1);
    expect(Number(window.localStorage.getItem(ACTIVITY_KEY))).toBeLessThan(clock - 5 * HOUR);
  });

  it('records activity at most every 30 seconds', () => {
    stop = startIdleWatch({ onIdle: vi.fn(), now });
    const set = vi.spyOn(Storage.prototype, 'setItem');
    for (let i = 0; i < 10; i++) {
      clock += 1000;
      window.dispatchEvent(new Event('mousemove'));
    }
    expect(set.mock.calls.filter((c) => c[0] === ACTIVITY_KEY).length).toBeLessThanOrEqual(1);
    set.mockRestore();
  });
});

describe('signing out for inactivity', () => {
  it('ends the session on the server, forgets the sign-in and the activity time, and goes to the login page with the reason', async () => {
    window.localStorage.setItem(AUTH_TOKEN_KEY, 'access');
    window.localStorage.setItem(AUTH_REFRESH_KEY, 'refresh');
    window.localStorage.setItem(AUTH_USER_KEY, '{}');
    markActive(1);
    const calls: string[] = [];
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async (url: unknown) => {
      calls.push(String(url));
      return new Response(JSON.stringify({ revoked: true }), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as typeof fetch;
    const redirect = vi.spyOn(sessionHooks, 'redirectToLogin').mockImplementation(() => undefined);
    try {
      await signOutIdle();
    } finally {
      globalThis.fetch = realFetch;
    }
    expect(calls).toEqual(['/api/v1/auth/logout']);
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem(AUTH_REFRESH_KEY)).toBeNull();
    expect(window.localStorage.getItem(AUTH_ACTIVITY_KEY)).toBeNull();
    expect(redirect).toHaveBeenCalledWith(expect.any(String), IDLE_REASON);
    redirect.mockRestore();
  });

  it('a normal sign-out also forgets the activity time, so the next login starts a fresh clock', () => {
    markActive(1);
    clearSession();
    expect(window.localStorage.getItem(AUTH_ACTIVITY_KEY)).toBeNull();
  });
});
