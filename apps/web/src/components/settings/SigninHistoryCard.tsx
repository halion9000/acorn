'use client';

/**
 * Settings > Profile: your own last twenty sign-ins, newest first, with how (password, passkey, Microsoft) and from which address. It is there so a sign-in you did not make stands out. Only your
 * own; nobody else sees it here, and it shows nobody else's.
 */
import useSWR from 'swr';
import { authFetch } from '@/lib/auth-session';

export interface Signin {
  at: string | null;
  method: string;
  ip: string | null;
}

const fetchSignins = (url: string): Promise<Signin[]> =>
  authFetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

/** "2026-11-10 09:30 UTC" from an ISO time, or "time not recorded" when there is none or it cannot be read (pure). */
export function signinTime(at: string | null): string {
  if (!at) return 'time not recorded';
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? 'time not recorded' : `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/** How many different addresses the list holds, as a sentence; null when no address was recorded (pure). */
export function addressesNote(signins: Signin[]): string | null {
  const distinct = new Set(signins.map((s) => s.ip).filter((ip): ip is string => !!ip));
  if (distinct.size === 0) return null;
  return distinct.size === 1 ? 'All from one address.' : `From ${distinct.size} different addresses.`;
}

export function SigninHistoryCard() {
  const { data, error } = useSWR<Signin[]>('/api/v1/auth/me/signins', fetchSignins, { revalidateOnFocus: false, shouldRetryOnError: false });
  const note = data ? addressesNote(data) : null;
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="signin-history">
      <h3 className="text-sm font-semibold text-gray-100">Your recent sign-ins</h3>
      <p className="mt-1 text-xs text-gray-400">The last twenty, newest first. If one is not yours, change your password and tell an administrator.</p>
      {error ? (
        <p data-testid="signin-problem" className="mt-2 text-xs text-gray-400">
          Your sign-ins could not be read. Try again later.
        </p>
      ) : null}
      {data && data.length === 0 ? <p className="mt-2 text-xs text-gray-400">No sign-in has been recorded yet. The next one will show here.</p> : null}
      {data && data.length > 0 ? (
        <>
          {note ? (
            <p className="mt-2 text-xs text-gray-300" data-testid="signin-addresses">
              {note}
            </p>
          ) : null}
          <ul className="mt-2 space-y-1 text-xs text-gray-300">
            {data.map((s, i) => (
              <li key={`${s.at}-${i}`} data-testid="signin-row">
                <span className="text-gray-500">{signinTime(s.at)}</span> · {s.method} · {s.ip ?? 'address not recorded'}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
