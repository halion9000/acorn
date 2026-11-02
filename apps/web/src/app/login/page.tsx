'use client';

/**
 * Desktop console login.
 *
 * Account name + password against ``POST /api/v1/auth/login`` (an email works only if the server has LOGIN_ALLOW_EMAIL on; it is off by default) for the open-source
 * console, or a passkey added under Settings > Profile.
 */

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { authApi, passkeyApi } from '@/lib/api';
import { getPasskey, isWebAuthnSupported } from '@/lib/webauthn';
import { ssoErrorMessage } from '@/lib/sso-messages';

/**
 * The server refuses further sign-ins (429) after too many failed attempts, and says how long to wait in its own sentence ("Too many failed sign-in attempts. Try again in about
 * 12 minutes."). Show that, not "API 429 Too Many Requests". Recognised by its fields rather than by class so this page does not depend on how the API client builds errors.
 */
function tooManyAttemptsMessage(err: unknown): string | null {
  const e = err as { status?: unknown; body?: unknown } | null;
  if (!e || e.status !== 429) return null;
  try {
    const detail = (JSON.parse(String(e.body)) as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail) return detail;
  } catch {
    /* not JSON: use the fallback */
  }
  return 'Too many failed sign-in attempts. Please wait a few minutes and try again.';
}

type Phase = 'idle' | 'pending' | 'success' | 'error';

export const dynamic = 'force-dynamic';

/**
 * Sanitize the ``?next=`` redirect target so a crafted link can't be used to
 * bounce an authenticated user to an attacker-controlled host.
 *
 * Only same-origin relative paths are allowed. Anything that looks like an
 * absolute URL (``http://``, ``//evil.com``), a JS scheme, or a path that
 * doesn't start with a single ``/`` is replaced with the dashboard default.
 */
function sanitizeNext(raw: string | null | undefined): string {
  const fallback = '/dashboard';
  if (!raw) return fallback;
  // Reject protocol-relative URLs (//evil.com) and backslash variants
  // (some browsers normalize \\ to //).
  if (raw.startsWith('//') || raw.startsWith('\\\\')) return fallback;
  // Require a single leading slash. This rejects ``http://...``,
  // ``javascript:...``, ``data:...``, ``mailto:...``, and bare paths
  // like ``dashboard`` (which would resolve relative to the current URL).
  if (!raw.startsWith('/')) return fallback;
  // Reject ``/\evil.com`` style tricks.
  if (raw.startsWith('/\\')) return fallback;
  return raw;
}

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const next = sanitizeNext(search?.get('next'));

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);

  const [sso, setSso] = useState<{ microsoft: boolean; password_login: string }>({ microsoft: false, password_login: 'all' });
  const ssoCode = search?.get('sso') ?? null;
  const [ssoError, setSsoError] = useState<string | null>(ssoErrorMessage(search?.get('sso_error')));
  const [finishing, setFinishing] = useState(Boolean(ssoCode));

  useEffect(() => {
    if (authApi.isAuthenticated() && !ssoCode) {
      router.replace(next);
    }
  }, [next, router, ssoCode]);

  useEffect(() => {
    let live = true;
    void authApi.ssoStatus().then((s) => {
      if (live) setSso(s);
    });
    return () => {
      live = false;
    };
  }, []);

  // Back from Microsoft with a one-time code: trade it for a session, then go where the person was headed.
  useEffect(() => {
    if (!ssoCode) return;
    let live = true;
    authApi
      .completeSso(ssoCode)
      .then(() => {
        if (live) router.replace(next);
      })
      .catch((err) => {
        if (!live) return;
        console.error('[login] sso failed', err);
        setFinishing(false);
        setSsoError('That sign-in link has expired or was already used. Start again.');
      });
    return () => {
      live = false;
    };
  }, [ssoCode, next, router]);

  // Sign in with a passkey. The account name is only a hint (an email, when it looks like one); with none, the browser offers the passkeys it holds.
  const passkeySupported = typeof window !== 'undefined' && isWebAuthnSupported();
  const passkeySignIn = async () => {
    if (phase === 'pending') return;
    setPhase('pending');
    setError(null);
    try {
      const hint = identifier.includes('@') ? identifier.trim() : undefined;
      const begin = await passkeyApi.authenticateBegin(hint);
      const credential = await getPasskey(begin.publicKey as unknown as Parameters<typeof getPasskey>[0]);
      const tokens = await passkeyApi.authenticateFinish(begin.challenge, credential as unknown as Record<string, unknown>);
      await authApi.completeWithTokens(tokens);
      setPhase('success');
      router.replace(next);
    } catch (err) {
      console.error('[login] passkey failed', err);
      setPhase('error');
      if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) setError('Cancelled. Try the passkey again, or use your password.');
      else setError(err instanceof Error && err.message ? err.message : 'Passkey sign-in failed.');
    }
  };

  const microsoftHref = `/api/v1/auth/sso/microsoft/login?next=${encodeURIComponent(next)}`;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (phase === 'pending') return;
    setPhase('pending');
    setError(null);

    try {
      await authApi.login(identifier.trim(), password);
      setPhase('success');
      router.replace(next);
    } catch (err) {
      console.error('[login] failed', err);
      setPhase('error');
      const message = err instanceof Error ? err.message : 'Login failed.';
      const locked = tooManyAttemptsMessage(err);
      // Map the common 401 to something a human understands.
      if (locked) {
        setError(locked);
      } else if (/401|incorrect/i.test(message)) {
        setError('Account name or password incorrect.');
      } else {
        setError(message);
      }
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 antialiased flex flex-col">
      <div className="flex-1 flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-md">
          {/* Brand */}
          <div className="flex flex-col items-center text-center mb-10">
            {/* Not a link: "/" is the project's public marketing site, which a private console has no reason to send people to. */}
            <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center mb-5" aria-hidden="true">
              <svg
                className="w-8 h-8 text-white"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.75}
                  d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
                />
              </svg>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Sign in to A.C.O.R.N
            </h1>
            <p className="text-sm text-zinc-400 mt-2 leading-relaxed">
              Open-source AI SOC console. Sign in with your tenant&rsquo;s account.
            </p>
          </div>

          {finishing ? (
            <p role="status" className="text-center text-sm text-zinc-400">
              Finishing sign-in…
            </p>
          ) : null}

          {sso.microsoft && !finishing ? (
            <div className="mb-6 space-y-3">
              <a
                href={microsoftHref}
                className="w-full border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-zinc-100 font-medium rounded-xl py-3 px-4 transition flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 21 21" aria-hidden="true">
                  <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                  <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                  <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                  <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
                </svg>
                <span>Sign in with Microsoft</span>
              </a>
              <p className="text-center text-xs text-zinc-500">
                {sso.password_login === 'admins' ? 'Administrators can also sign in with an account name and password.' : 'Or sign in with an account name and password.'}
              </p>
            </div>
          ) : null}

          {ssoError ? (
            <div role="alert" className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-xs text-red-300">
              {ssoError}
            </div>
          ) : null}

          {/* Form */}
          <form onSubmit={submit} className={finishing ? 'hidden' : 'space-y-4'} noValidate>
            <label className="block">
              <span className="block text-xs uppercase tracking-wider text-zinc-500 mb-2">
                Account name
              </span>
              <input
                type="text"
                autoComplete="username"
                inputMode="text"
                autoCapitalize="off"
                spellCheck={false}
                placeholder="your.account.name"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                disabled={phase === 'pending'}
                required
                className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 disabled:opacity-60"
              />
            </label>

            <label className="block">
              <span className="block text-xs uppercase tracking-wider text-zinc-500 mb-2">
                Password
              </span>
              <input
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={phase === 'pending'}
                required
                className="w-full bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 disabled:opacity-60"
              />
            </label>

            <button
              type="submit"
              disabled={phase === 'pending' || !identifier || !password}
              className="w-full bg-indigo-500 hover:bg-indigo-400 active:bg-indigo-600 text-white font-medium rounded-xl py-3 px-4 transition flex items-center justify-center gap-2 disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              {phase === 'pending' ? (
                <>
                  <svg
                    className="w-4 h-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="3"
                    />
                    <path
                      className="opacity-90"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                    />
                  </svg>
                  <span>Signing in…</span>
                </>
              ) : (
                <span>Sign in</span>
              )}
            </button>

            {error ? (
              <div
                role="alert"
                className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2.5 text-xs text-red-300"
              >
                {error}
              </div>
            ) : null}
          </form>

          {/* Footer hints */}
          <div className="mt-8 space-y-3 text-center">
            {passkeySupported ? (
              <button
                type="button"
                onClick={() => void passkeySignIn()}
                disabled={phase === 'pending'}
                className="w-full border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60 text-zinc-100 text-sm font-medium rounded-xl py-2.5 px-4 transition"
              >
                Sign in with a passkey
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="px-6 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4 text-center">
        <p className="text-[10px] text-zinc-700 uppercase tracking-widest">
          A.C.O.R.N · MIT-licensed · Open-source AI SOC
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
