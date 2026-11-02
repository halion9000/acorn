'use client';

/**
 * Settings > Profile: the passkeys on this account. List, add one on this device, revoke one (after asking, naming it). The same three calls the phone app's settings page makes;
 * a list that cannot load says so instead of showing an empty list that would read as "none enrolled".
 */
import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { passkeyApi, type PasskeyCredential } from '@/lib/api';
import { createPasskey, isWebAuthnSupported } from '@/lib/responder/webauthn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { safeFormat } from '@/lib/safe-date';

function problemOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function PasskeysCard() {
  const [items, setItems] = useState<PasskeyCredential[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [toRevoke, setToRevoke] = useState<PasskeyCredential | null>(null);
  const [revoking, setRevoking] = useState(false);
  const supported = isWebAuthnSupported();

  const load = useCallback(async () => {
    try {
      const res = await passkeyApi.list();
      setItems(res.items);
      setLoadProblem(null);
    } catch (err) {
      setItems(null);
      setLoadProblem(problemOf(err, 'Could not load your passkeys.'));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const enroll = async () => {
    setEnrolling(true);
    try {
      const begin = await passkeyApi.registerBegin(begin_name());
      const credential = await createPasskey(begin.publicKey as unknown as Parameters<typeof createPasskey>[0]);
      await passkeyApi.registerFinish(begin.challenge, credential as unknown as Record<string, unknown>);
      toast.success('Passkey added on this device');
      await load();
    } catch (err) {
      if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) toast('Cancelled');
      else toast.error(problemOf(err, 'Could not add the passkey.'));
    } finally {
      setEnrolling(false);
    }
  };

  const revoke = async () => {
    if (!toRevoke) return;
    setRevoking(true);
    try {
      await passkeyApi.delete(toRevoke.id);
      toast.success('Passkey revoked');
      setToRevoke(null);
      await load();
    } catch (err) {
      toast.error(problemOf(err, 'Could not revoke the passkey.'));
    } finally {
      setRevoking(false);
    }
  };

  return (
    <section aria-labelledby="passkeys-heading" className="rounded-lg border border-gray-800 bg-gray-950/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="passkeys-heading" className="text-sm font-semibold text-gray-100">
            Passkeys
          </h3>
          <p className="mt-0.5 text-xs text-gray-500">Sign in with your fingerprint, face or a security key instead of a password. Add one on each device you use.</p>
        </div>
        <button
          type="button"
          disabled={!supported || enrolling}
          onClick={() => void enroll()}
          title={supported ? undefined : 'This browser does not support passkeys'}
          className="shrink-0 rounded-lg border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {enrolling ? 'Adding…' : 'Add a passkey'}
        </button>
      </div>

      {loadProblem ? (
        <p role="alert" className="mt-3 text-xs text-red-300">
          {loadProblem}
        </p>
      ) : items === null ? (
        <p className="mt-3 text-xs text-gray-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="mt-3 text-xs text-gray-400">No passkeys yet. You sign in with your password.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-800">
          {items.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm text-gray-200">{p.device_name}</p>
                <p className="text-xs text-gray-500">
                  Added {safeFormat(p.created_at, 'PP')} · {p.last_used_at ? `last used ${safeFormat(p.last_used_at, 'PP')}` : 'never used'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setToRevoke(p)}
                aria-label={`Revoke ${p.device_name}`}
                className="shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-gray-800"
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={toRevoke !== null}
        title="Revoke this passkey?"
        message={`${toRevoke?.device_name ?? 'This passkey'} will no longer sign you in. If it is your only way in besides the password, make sure you still know the password.`}
        confirmLabel="Revoke"
        destructive
        busy={revoking}
        onConfirm={() => void revoke()}
        onCancel={() => setToRevoke(null)}
      />
    </section>
  );
}

function begin_name(): string {
  const hint = typeof navigator !== 'undefined' && navigator.userAgent ? navigator.userAgent.split(' ').slice(-1)[0] : 'Browser';
  return `${hint} – web`;
}
