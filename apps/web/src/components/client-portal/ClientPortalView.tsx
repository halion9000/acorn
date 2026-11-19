'use client';

/**
 * The client dashboard (the Rewst End User Dashboard, rebuilt): what a person at a customer sees after signing in. Their own company's tickets, hours and satisfaction, and nothing else: no sidebar, no
 * staff pages, no client picker (the server decides which company they are; nothing here names one). A person who has not set up an authenticator app is asked to do that first: the server holds the summary back until they have.
 */
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';

import { SetupQr } from '@/components/settings/TotpCard';
import { ClientSummaryBody } from '@/components/metrics/ClientSummaryView';
import { PERIODS } from '@/components/metrics/TicketMetricsView';
import { apiErrorDetail, authApi, clientPortalApi, totpApi, type ClientPortalSummary } from '@/lib/api';
import { revokeServerSession } from '@/lib/auth-session';

const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;
const input = 'w-full rounded-md border border-gray-700 bg-gray-950/60 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600';

/** What the server's refusal means for this page (pure): the authenticator app is missing, the company is not linked, or the person is not a client sign-in at all. */
export function refusalKind(status: number, detail: string): 'mfa' | 'unlinked' | 'not-client' | 'other' {
  if (status === 403 && detail.startsWith('mfa_setup_required')) return 'mfa';
  if (status === 403) return 'not-client';
  if (status === 409) return 'unlinked';
  return 'other';
}

export function SetupAuthenticator({ onDone }: { onDone: () => void }) {
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await totpApi.enrol();
      setSetup({ secret: r.secret, uri: r.otpauth_uri });
    } catch (err) {
      setProblem(apiErrorDetail(err) ?? 'Could not start the setup.');
    } finally {
      setBusy(false);
    }
  };
  const confirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const r = await totpApi.confirm(code.trim());
      setRecovery(r.recovery_codes);
    } catch (err) {
      setProblem(apiErrorDetail(err) ?? 'That code is not right.');
    } finally {
      setBusy(false);
    }
  };
  if (recovery)
    return (
      <div className="space-y-3" data-testid="portal-recovery">
        <p className="text-sm text-gray-200">The authenticator app is on. Keep these recovery codes somewhere safe: each works once if you lose your phone, and they are not shown again.</p>
        <ul className="grid grid-cols-2 gap-1 font-mono text-sm text-gray-100">
          {recovery.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <button type="button" className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500" onClick={onDone}>
          I saved them, open the dashboard
        </button>
      </div>
    );
  return (
    <div className="space-y-3" data-testid="portal-mfa-setup">
      <p className="text-sm text-gray-200">
        To keep your company&apos;s numbers private, this dashboard needs a second step when you sign in. Set up an authenticator app (Microsoft Authenticator, Google Authenticator or similar).
      </p>
      {!setup ? (
        <button type="button" disabled={busy} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50" onClick={() => void start()}>
          Set up the authenticator app
        </button>
      ) : (
        <form className="space-y-3" onSubmit={(e) => void confirm(e)}>
          <SetupQr uri={setup.uri} />
          <p className="text-xs text-gray-400">
            Cannot scan it? Type this key into the app: <span className="font-mono text-gray-200">{setup.secret}</span>
          </p>
          <label className="block text-sm text-gray-300">
            The 6-digit code the app shows
            <input className={`${input} mt-1`} inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || !code.trim()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50">
            Turn it on
          </button>
        </form>
      )}
      {problem && (
        <p role="alert" className="text-sm text-amber-300">
          {problem}
        </p>
      )}
    </div>
  );
}

export function ClientPortalView() {
  const router = useRouter();
  const [months, setMonths] = useState<number>(3);
  const [data, setData] = useState<ClientPortalSummary | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'mfa' | 'unlinked' | 'not-client' | 'other'>('loading');
  const [message, setMessage] = useState('');

  const load = useCallback(async (m: number) => {
    try {
      setData(await clientPortalApi.summary(m));
      setState('ok');
    } catch (err) {
      const status = (err as { status?: number } | null)?.status ?? 0;
      const detail = apiErrorDetail(err) ?? (err instanceof Error ? err.message : 'Could not load.');
      setMessage(detail.replace(/^mfa_setup_required:\s*/, ''));
      setState(refusalKind(status, detail));
    }
  }, []);
  useEffect(() => {
    void load(months);
  }, [load, months]);

  const signOut = async () => {
    const server = await revokeServerSession();
    authApi.logout();
    router.replace('/login');
    if (!server.ended) toast.error('Signed out on this device, but the server could not end the session.');
  };

  return (
    <div className="mx-auto min-h-screen max-w-5xl bg-surface-base" data-testid="client-portal">
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <p className="text-sm font-semibold text-white">{data?.client_name ?? 'Your IT dashboard'}</p>
        <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800" onClick={() => void signOut()}>
          Sign out
        </button>
      </header>
      <main className="space-y-5 p-6">
        {state === 'loading' && (
          <p role="status" className="text-sm text-gray-500">
            Loading…
          </p>
        )}
        {state === 'mfa' && <SetupAuthenticator onDone={() => void load(months)} />}
        {state === 'unlinked' && (
          <p role="alert" className="text-sm text-amber-300">
            {message}
          </p>
        )}
        {state === 'not-client' && (
          <p role="alert" className="text-sm text-amber-300">
            This page is for client dashboard sign-ins. Staff use the console.
          </p>
        )}
        {state === 'other' && (
          <p role="alert" className="text-sm text-amber-300">
            {message}
          </p>
        )}
        {state === 'ok' && data && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold text-white">Your IT summary</h1>
                <p className="mt-1 text-sm text-gray-400">
                  The last {months === 1 ? 'month' : `${months} months`} of tickets, hours and satisfaction for {data.client_name}, as of the last daily update.
                </p>
              </div>
              <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 print:hidden" onClick={() => window.print()}>
                Print or save as PDF
              </button>
            </div>
            <div role="group" aria-label="Period" className="flex gap-1 print:hidden">
              {PERIODS.map((p) => (
                <button key={p} type="button" aria-pressed={months === p} className={pill(months === p)} onClick={() => setMonths(p)}>
                  {p === 1 ? 'Last month' : `Last ${p} months`}
                </button>
              ))}
            </div>
            <ClientSummaryBody empty={data.received_at === null} t={data.tickets} l={data.hours} sat={data.satisfaction} />
          </>
        )}
      </main>
    </div>
  );
}
