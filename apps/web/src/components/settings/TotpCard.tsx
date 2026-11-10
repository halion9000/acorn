'use client';

/**
 * Settings > Profile: the authenticator-app code (Google Authenticator, Microsoft Authenticator, any app that takes a standard key) a password sign-in asks for. Set up in three steps: get a key,
 * type the 6-digit code the app shows, save the recovery codes (shown once). Turning it off needs the password and a current code, so a stolen session alone cannot remove the protection.
 * Passkeys (above) and Microsoft sign-in are separate ways in and are not affected.
 */
import { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';
import toast from 'react-hot-toast';
import { apiErrorDetail, totpApi, type TotpStatus } from '@/lib/api';

function problemOf(err: unknown, fallback: string): string {
  return apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : fallback);
}

const input = 'w-full rounded-md border border-gray-700 bg-gray-950/60 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-600';
const ghost = 'rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-800';

/** The setup address as a QR code the authenticator app scans (drawn in the browser; the secret never leaves the page). Nothing is shown if it cannot be drawn: the typed key below always works. */
export function SetupQr({ uri }: { uri: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    QRCode.toString(uri, { type: 'svg', margin: 1, width: 176, errorCorrectionLevel: 'M' })
      .then((s) => live && setSvg(s))
      .catch(() => live && setSvg(null));
    return () => {
      live = false;
    };
  }, [uri]);
  if (!svg) return null;
  // The markup is produced by the QR library from the address above and holds only shapes, no scripts or text from outside.
  return <div role="img" aria-label="QR code for the authenticator app" data-testid="totp-qr" className="inline-block rounded bg-white p-1" dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function TotpCard() {
  const [status, setStatus] = useState<TotpStatus | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await totpApi.status());
      setLoadProblem(null);
    } catch (err) {
      setLoadProblem(problemOf(err, 'Could not load the authenticator app setting.'));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const start = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await totpApi.enrol();
      setSetup({ secret: r.secret, uri: r.otpauth_uri });
      setCode('');
    } catch (err) {
      setProblem(problemOf(err, 'Could not start the setup.'));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await totpApi.confirm(code.trim());
      setRecovery(r.recovery_codes);
      setSetup(null);
      setCode('');
      await load();
    } catch (err) {
      setProblem(problemOf(err, 'That code is not right.'));
    } finally {
      setBusy(false);
    }
  };

  const replaceCodes = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const r = await totpApi.newRecoveryCodes(password, code.trim());
      setRecovery(r.recovery_codes);
      setReplacing(false);
      setPassword('');
      setCode('');
      await load();
    } catch (err) {
      setProblem(problemOf(err, 'The password or the code is not right.'));
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await totpApi.disable(password, code.trim());
      toast.success('Authenticator app turned off.');
      setDisabling(false);
      setPassword('');
      setCode('');
      await load();
    } catch (err) {
      setProblem(problemOf(err, 'The password or the code is not right.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Authenticator app" className="rounded-lg border border-gray-800 bg-gray-950/40 p-4 space-y-3" data-testid="totp-card">
      <div>
        <h3 className="text-sm font-medium text-gray-100">Authenticator app</h3>
        <p className="text-xs text-gray-500">An extra code from your phone when you sign in with a password. Works with Google Authenticator and Microsoft Authenticator.</p>
      </div>

      {loadProblem ? (
        <p role="alert" className="text-sm text-red-300">
          {loadProblem}
        </p>
      ) : status === null ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : recovery ? (
        <div className="space-y-2" data-testid="totp-recovery">
          <p className="text-sm text-emerald-300">Authenticator app is on.</p>
          <p className="text-xs text-amber-300">Save these recovery codes now. Each works once if you lose your phone, and they are not shown again.</p>
          <ul className="grid grid-cols-2 gap-1 font-mono text-sm text-gray-200">
            {recovery.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <button type="button" onClick={() => setRecovery(null)} className={ghost}>
            I have saved them
          </button>
        </div>
      ) : status.enabled ? (
        <div className="space-y-2">
          <p className="text-sm text-emerald-300" data-testid="totp-on">
            On. {status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? '' : 's'} left.
          </p>
          {replacing ? (
            <div className="space-y-2" data-testid="totp-replace">
              <p className="text-xs text-gray-400">New codes replace the old ones: any you have saved stop working.</p>
              <input aria-label="Current password" type="password" autoComplete="current-password" placeholder="Your password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
              <input aria-label="Code for new recovery codes" type="text" autoComplete="one-time-code" placeholder="Current code from the app" value={code} onChange={(e) => setCode(e.target.value)} className={input} />
              <div className="flex gap-2">
                <button type="button" disabled={busy || !password || !code.trim()} onClick={() => void replaceCodes()} className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
                  Make new recovery codes
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setReplacing(false);
                    setProblem(null);
                  }}
                  className={ghost}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : disabling ? (
            <div className="space-y-2">
              <input aria-label="Current password" type="password" autoComplete="current-password" placeholder="Your password" value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
              <input aria-label="Code to turn it off" type="text" autoComplete="one-time-code" placeholder="Current code or a recovery code" value={code} onChange={(e) => setCode(e.target.value)} className={input} />
              <div className="flex gap-2">
                <button type="button" disabled={busy || !password || !code.trim()} onClick={() => void turnOff()} className="rounded bg-red-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
                  Turn off
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setDisabling(false);
                    setProblem(null);
                  }}
                  className={ghost}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <button type="button" onClick={() => setReplacing(true)} className={ghost}>
                New recovery codes…
              </button>
              <button type="button" onClick={() => setDisabling(true)} className={ghost}>
                Turn off…
              </button>
            </div>
          )}
        </div>
      ) : setup ? (
        <div className="space-y-2" data-testid="totp-setup">
          <SetupQr uri={setup.uri} />
          <ol className="list-decimal pl-5 text-xs text-gray-400 space-y-1">
            <li>In your authenticator app choose Add account and scan the QR code above, or enter a setup key (or setup code) by hand.</li>
            <li>
              Account name: A.C.O.R.N. Key:{' '}
              <code className="select-all rounded bg-gray-900 px-1 py-0.5 text-gray-100" data-testid="totp-secret">
                {setup.secret}
              </code>{' '}
              (time based).
            </li>
            <li>Type the 6-digit code the app now shows:</li>
          </ol>
          <input aria-label="Code from the app" type="text" inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} className={input} />
          <button type="button" disabled={busy || !code.trim()} onClick={() => void confirm()} className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
            Turn on
          </button>
        </div>
      ) : (
        <button type="button" disabled={busy} onClick={() => void start()} className={`${ghost} disabled:opacity-50`}>
          Set up an authenticator app
        </button>
      )}

      {problem ? (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
